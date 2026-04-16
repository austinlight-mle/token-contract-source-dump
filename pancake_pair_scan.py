#!/usr/bin/env python3
"""
Scan PancakeSwap V2 pair contracts from most recent to oldest,
filter by USD liquidity, and output qualifying contracts to
pair_contracts.txt (full BscScan URLs), contracts.json (detailed info),
and new_tokens.txt (addresses of new tokens, excluding WBNB/USDT).

Usage:
    python pancake_pair_scan.py                                    # scan all pairs (recent first)
    python pancake_pair_scan.py --limit 500                        # scan only the latest 500 pairs
    python pancake_pair_scan.py --index 123456                     # scan a single pair at index 123456
    python pancake_pair_scan.py --start-index 100000               # start from pair index 100000
    python pancake_pair_scan.py --end-index 50000                  # stop at pair index 50000
    python pancake_pair_scan.py --start-index 100000 --end-index 99000  # scan a specific range
    python pancake_pair_scan.py --min-liq 50000                    # set minimum liquidity to $50,000
"""

import argparse
import json
import os
import sys
import time
import requests
from web3 import Web3
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

FACTORY_ADDRESS = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"

FACTORY_ABI = [
    {"inputs": [], "name": "allPairsLength", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "name": "allPairs", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
]

PAIR_ABI = [
    {"inputs": [], "name": "token0", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "getReserves", "outputs": [{"internalType": "uint112", "name": "_reserve0", "type": "uint112"}, {"internalType": "uint112", "name": "_reserve1", "type": "uint112"}, {"internalType": "uint32", "name": "_blockTimestampLast", "type": "uint32"}], "stateMutability": "view", "type": "function"},
]

ERC20_ABI = [
    {"inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "name", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
]

DEXSCREENER_PAIRS_URL = "https://api.dexscreener.com/latest/dex/pairs/bsc/{}"
DEXSCREENER_TOKENS_URL = "https://api.dexscreener.com/tokens/v1/bsc/{}"
BSCSCAN_ADDRESS_URL = "https://bscscan.com/address/{}"
DEFAULT_MIN_LIQUIDITY = 10_000

# Well-known base token addresses (lowercased) — these are excluded from new_tokens.txt
KNOWN_BASE_TOKENS = {
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
    "0x55d398326f99059ff775485246999027b3197955",  # USDT
}


def get_token_price_usd(address: str, cache: dict) -> float | None:
    """Get token price in USD from DexScreener tokens endpoint, with caching."""
    addr_lower = address.lower()
    if addr_lower in cache:
        return cache[addr_lower]
    try:
        resp = requests.get(DEXSCREENER_TOKENS_URL.format(address), timeout=10)
        resp.raise_for_status()
        pairs = resp.json()
        if isinstance(pairs, list) and pairs:
            price = pairs[0].get("priceUsd")
            if price is not None:
                cache[addr_lower] = float(price)
                return cache[addr_lower]
    except Exception:
        pass
    cache[addr_lower] = None
    return None


def query_pair_dexscreener(pair_address: str):
    """Query DexScreener for pair info. Returns dict or None."""
    try:
        resp = requests.get(DEXSCREENER_PAIRS_URL.format(pair_address), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("pair") or (data.get("pairs") or [None])[0]
    except Exception:
        return None


def calc_liquidity_from_reserves(w3, pair_address, price_cache):
    """Fallback: calculate liquidity from on-chain reserves + DexScreener token prices."""
    try:
        pair = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)
        t0 = pair.functions.token0().call()
        t1 = pair.functions.token1().call()
        reserves = pair.functions.getReserves().call()

        tok0 = w3.eth.contract(address=Web3.to_checksum_address(t0), abi=ERC20_ABI)
        tok1 = w3.eth.contract(address=Web3.to_checksum_address(t1), abi=ERC20_ABI)
        dec0 = tok0.functions.decimals().call()
        dec1 = tok1.functions.decimals().call()
        sym0 = tok0.functions.symbol().call()
        sym1 = tok1.functions.symbol().call()
        name0 = tok0.functions.name().call()
        name1 = tok1.functions.name().call()

        p0 = get_token_price_usd(t0, price_cache)
        p1 = get_token_price_usd(t1, price_cache)
        time.sleep(0.25)

        val = 0.0
        if p0 is not None:
            val += (reserves[0] / 10**dec0) * p0
        if p1 is not None:
            val += (reserves[1] / 10**dec1) * p1

        token_a = {"address": t0, "name": name0, "symbol": sym0}
        token_b = {"address": t1, "name": name1, "symbol": sym1}
        return val, token_a, token_b
    except Exception:
        return None, None, None


def get_new_token_address(contract: dict) -> str | None:
    """Return the address of the non-base token in the pair (i.e. not WBNB/USDT).
    If neither token is a known base token, return token_a's address.
    If both are known base tokens, return None."""
    addr_a = (contract.get("token_a") or {}).get("address", "").lower()
    addr_b = (contract.get("token_b") or {}).get("address", "").lower()
    a_is_base = addr_a in KNOWN_BASE_TOKENS
    b_is_base = addr_b in KNOWN_BASE_TOKENS
    if a_is_base and b_is_base:
        return None
    if a_is_base:
        return contract["token_b"]["address"]
    return contract["token_a"]["address"]


def write_outputs(contracts: list, txt_path: str, json_path: str, tokens_path: str):
    """Write results to pair_contracts.txt, contracts.json, and new_tokens.txt."""
    with open(txt_path, "w", encoding="utf-8") as f:
        for c in contracts:
            f.write(f"{BSCSCAN_ADDRESS_URL.format(c['address'])}\n")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(contracts, f, indent=2, ensure_ascii=False)
    with open(tokens_path, "w", encoding="utf-8") as f:
        for c in contracts:
            token_addr = get_new_token_address(c)
            if token_addr:
                f.write(f"{BSCSCAN_ADDRESS_URL.format(token_addr)}\n")


def main():
    parser = argparse.ArgumentParser(description="Scan PancakeSwap V2 pairs by liquidity")
    parser.add_argument("--limit", type=int, default=0, help="Max number of pairs to scan (0 = all)")
    parser.add_argument("--index", type=int, default=-1,
                        help="Scan a single pair at this index")
    parser.add_argument("--start-index", type=int, default=-1,
                        help="Start scanning from this pair index (default: latest)")
    parser.add_argument("--end-index", type=int, default=0,
                        help="Stop scanning at this pair index, inclusive (default: 0)")
    parser.add_argument("--min-liq", type=float, default=DEFAULT_MIN_LIQUIDITY,
                        help=f"Minimum liquidity in USD (default: {DEFAULT_MIN_LIQUIDITY:,})")
    args = parser.parse_args()

    rpc_url = os.getenv("BSC_RPC_URL")
    if not rpc_url:
        print("Error: BSC_RPC_URL not found in .env")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print("Error: Cannot connect to BSC RPC")
        sys.exit(1)
    print("Connected to BSC RPC")

    factory = w3.eth.contract(
        address=Web3.to_checksum_address(FACTORY_ADDRESS), abi=FACTORY_ABI
    )
    total_pairs = factory.functions.allPairsLength().call()
    print(f"Total registered pairs: {total_pairs:,}")

    if args.index >= 0:
        start_index = min(args.index, total_pairs - 1)
        end_index = start_index
    else:
        start_index = args.start_index if args.start_index >= 0 else total_pairs - 1
        start_index = min(start_index, total_pairs - 1)
        end_index = max(args.end_index, 0)
        if args.limit > 0:
            end_index = max(start_index - args.limit + 1, end_index)
    scan_count = start_index - end_index + 1
    min_liq = args.min_liq
    print(f"Scanning from index {start_index:,} to {end_index:,} ({scan_count:,} pairs) | Min liquidity: ${min_liq:,.0f}\n")

    contracts: list[dict] = []
    price_cache: dict[str, float | None] = {}
    txt_path = "pair_contracts.txt"
    json_path = "contracts.json"
    tokens_path = "new_tokens.txt"
    log_path = "scan.log"

    # Log scan start
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(f"[{datetime.now(timezone.utc).isoformat()}] START start_index={start_index} end_index={end_index}\n")

    for n, i in enumerate(range(start_index, end_index - 1, -1), 1):
        try:
            pair_address = factory.functions.allPairs(i).call()
        except Exception as e:
            print(f"[{n}/{scan_count}] Error fetching pair index {i}: {e}")
            continue

        print(f"[{n}/{scan_count}] Pair #{i} {pair_address} ", end="", flush=True)

        # --- Try DexScreener pairs endpoint first ---
        pair_data = query_pair_dexscreener(pair_address)

        if pair_data:
            liquidity_usd = (pair_data.get("liquidity") or {}).get("usd") or 0
            base = pair_data.get("baseToken", {})
            quote = pair_data.get("quoteToken", {})
            token_a = {"address": base.get("address", ""), "name": base.get("name", ""), "symbol": base.get("symbol", "")}
            token_b = {"address": quote.get("address", ""), "name": quote.get("name", ""), "symbol": quote.get("symbol", "")}
            created_at = pair_data.get("pairCreatedAt")
            registered = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc).isoformat() if created_at else ""
        else:
            # --- Fallback: on-chain reserves + DexScreener token prices ---
            liquidity_usd, token_a, token_b = calc_liquidity_from_reserves(w3, pair_address, price_cache)
            if liquidity_usd is None:
                print("⏭ no data")
                time.sleep(0.25)
                continue
            registered = ""

        if liquidity_usd < min_liq:
            print(f"${liquidity_usd:,.0f} ⏭ below threshold")
            time.sleep(0.25)
            continue

        sym_a = token_a.get("symbol", "?") if token_a else "?"
        sym_b = token_b.get("symbol", "?") if token_b else "?"
        print(f"${liquidity_usd:,.0f} ✓ {sym_a}/{sym_b}")

        contracts.append({
            "index": i,
            "address": pair_address,
            "price_usd": round(liquidity_usd, 2),
            "token_a": token_a,
            "token_b": token_b,
            "registered": registered,
        })

        # Write incrementally so partial results are saved
        write_outputs(contracts, txt_path, json_path, tokens_path)
        time.sleep(0.25)

    print(f"\nDone! Found {len(contracts)} pairs with liquidity >= ${min_liq:,.0f}")
    print(f"Results saved to {txt_path}, {json_path}, and {tokens_path}")

    # Log scan end
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(f"[{datetime.now(timezone.utc).isoformat()}] END   start_index={start_index} end_index={end_index} found={len(contracts)}\n")


if __name__ == "__main__":
    main()
