#!/usr/bin/env python3
"""
Dump smart contract source code and metadata from Etherscan-compatible APIs.
Usage:
    python dump_contract.py                                        # prompts for address and chain
    python dump_contract.py --contract 0xADDRESS --chain bsc       # specify both
    python dump_contract.py --contract "https://bscscan.com/..."   # auto-detects chain from URL
"""

import argparse
import json
import os
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"

CHAIN_IDS = {
    "eth": 1,
    "bsc": 56,
    "polygon": 137,
    "arbitrum": 42161,
    "optimism": 10,
    "avalanche": 43114,
    "fantom": 250,
    "base": 8453,
}


def get_contract_source(chain_id: int, address: str, api_key: str) -> dict:
    """Fetch contract source code from Etherscan V2 API."""
    params = {
        "chainid": chain_id,
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": api_key,
    }
    resp = requests.get(ETHERSCAN_V2_BASE, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1" or not data.get("result"):
        msg = data.get("result", data.get("message", "Unknown error"))
        print(f"Error: {msg}")
        sys.exit(1)
    return data["result"][0]


def parse_source_files(source_code: str) -> dict[str, str]:
    """
    Parse SourceCode field. Handles:
    - Plain solidity source (single file)
    - JSON standard input wrapped in double braces {{...}}
    - JSON standard input without double braces
    """
    source_code = source_code.strip()

    # Multi-file: wrapped in {{ }}
    if source_code.startswith("{{") and source_code.endswith("}}"):
        source_code = source_code[1:-1]  # remove outer braces

    # Try parsing as JSON (standard input format)
    try:
        parsed = json.loads(source_code)
        if isinstance(parsed, dict):
            # Standard JSON input with "sources" key
            if "sources" in parsed:
                return {
                    name: src["content"]
                    for name, src in parsed["sources"].items()
                }
            # Possibly {filename: {content: ...}} directly
            files = {}
            for name, value in parsed.items():
                if isinstance(value, dict) and "content" in value:
                    files[name] = value["content"]
            if files:
                return files
    except (json.JSONDecodeError, TypeError):
        pass

    # Single file - return as-is
    return {"contract.sol": source_code}


def dump_contract(address: str, chain: str):
    """Fetch and dump contract source code and metadata."""
    api_key = os.getenv("ETHERSCAN_API")
    if not api_key:
        print("Error: ETHERSCAN_API not found in .env file")
        sys.exit(1)

    chain_id = CHAIN_IDS.get(chain)
    if not chain_id:
        print(f"Error: Unsupported chain '{chain}'. Supported: {', '.join(CHAIN_IDS)}")
        sys.exit(1)

    print(f"Fetching contract {address} from {chain} (chainid={chain_id})...")
    result = get_contract_source(chain_id, address, api_key)

    contract_name = result.get("ContractName", "Unknown")
    print(f"Contract: {contract_name}")

    # Create output directory
    out_dir = Path("contracts") / address
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Dump source files
    source_code = result.get("SourceCode", "")
    if source_code:
        source_files = parse_source_files(source_code)
        sources_dir = out_dir / "sources"
        sources_dir.mkdir(exist_ok=True)
        for filename, content in source_files.items():
            # Preserve directory structure from source names like @openzeppelin/contracts/...
            file_path = sources_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            print(f"  Saved: sources/{filename}")
    else:
        print("  No source code available (contract may not be verified)")

    # 2. Dump ABI
    abi_raw = result.get("ABI", "")
    if abi_raw and abi_raw != "Contract source code not verified":
        try:
            abi = json.loads(abi_raw)
            (out_dir / "abi.json").write_text(json.dumps(abi, indent=2), encoding="utf-8")
            print("  Saved: abi.json")
        except json.JSONDecodeError:
            (out_dir / "abi.txt").write_text(abi_raw, encoding="utf-8")
            print("  Saved: abi.txt")

    # 3. Dump settings / metadata
    settings = {
        "ContractName": result.get("ContractName", ""),
        "CompilerVersion": result.get("CompilerVersion", ""),
        "OptimizationUsed": result.get("OptimizationUsed", ""),
        "Runs": result.get("Runs", ""),
        "ConstructorArguments": result.get("ConstructorArguments", ""),
        "EVMVersion": result.get("EVMVersion", ""),
        "Library": result.get("Library", ""),
        "LicenseType": result.get("LicenseType", ""),
        "Proxy": result.get("Proxy", ""),
        "Implementation": result.get("Implementation", ""),
        "SwarmSource": result.get("SwarmSource", ""),
    }
    (out_dir / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print("  Saved: settings.json")

    # 4. Dump bytecode via eth_getCode
    bytecode = fetch_bytecode(chain_id, address, api_key)
    if bytecode and bytecode != "0x":
        (out_dir / "bytecode.txt").write_text(bytecode, encoding="utf-8")
        print("  Saved: bytecode.txt")

    # 5. Dump constructor arguments if available
    constructor_args = result.get("ConstructorArguments", "")
    if constructor_args:
        (out_dir / "constructor_args.txt").write_text(constructor_args, encoding="utf-8")
        print("  Saved: constructor_args.txt")

    print(f"\nDone! Files saved to: {out_dir}")


def fetch_bytecode(chain_id: int, address: str, api_key: str) -> str:
    """Fetch deployed bytecode via eth_getCode proxy."""
    params = {
        "chainid": chain_id,
        "module": "proxy",
        "action": "eth_getCode",
        "address": address,
        "tag": "latest",
        "apikey": api_key,
    }
    try:
        resp = requests.get(ETHERSCAN_V2_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", "")
    except Exception:
        return ""


def detect_chain_from_address_input(address_input: str) -> tuple[str, str]:
    """If user pastes a full URL like https://bscscan.com/address/0x..., extract chain and address."""
    address_input = address_input.strip()
    chain_map = {
        "etherscan.io": "eth",
        "bscscan.com": "bsc",
        "polygonscan.com": "polygon",
        "arbiscan.io": "arbitrum",
        "optimistic.etherscan.io": "optimism",
        "snowtrace.io": "avalanche",
        "ftmscan.com": "fantom",
        "basescan.org": "base",
    }
    for domain, chain in chain_map.items():
        if domain in address_input:
            # Extract address from URL
            parts = address_input.rstrip("/").split("/")
            for i, part in enumerate(parts):
                if part == "address" and i + 1 < len(parts):
                    addr = parts[i + 1].split("#")[0].split("?")[0]
                    return chain, addr
    return "", address_input


def main():
    parser = argparse.ArgumentParser(description="Dump smart contract source from Etherscan")
    parser.add_argument("--contract", help="Contract address or full URL")
    parser.add_argument("--chain", help=f"Chain: {', '.join(CHAIN_IDS)}")
    args = parser.parse_args()

    address = args.contract
    chain = args.chain

    if not address:
        address = input("Enter contract address or full URL: ").strip()

    if not address:
        print("Error: No address provided")
        sys.exit(1)

    # Auto-detect chain from URL
    detected_chain, parsed_address = detect_chain_from_address_input(address)
    if detected_chain:
        chain = detected_chain
        address = parsed_address
        print(f"Detected chain: {chain}")

    # If chain still not set, prompt the user
    if not chain:
        print(f"Supported chains: {', '.join(CHAIN_IDS)}")
        chain = input("Enter chain: ").strip().lower()

    if not chain or chain not in CHAIN_IDS:
        print(f"Error: Invalid chain '{chain}'. Supported: {', '.join(CHAIN_IDS)}")
        sys.exit(1)

    # Normalize address
    if not address.startswith("0x"):
        address = "0x" + address

    dump_contract(address, chain)


if __name__ == "__main__":
    main()
