# Smart Contract Source Dumper

Dump verified smart contract source code and metadata from any EVM-compatible chain using the Etherscan V2 API.

## Setup

```bash
pip install -r requirements.txt
```

Add your Etherscan API key to `.env`:

```
ETHERSCAN_API=your_api_key_here
```

## Usage

```bash
# Interactive prompt (asks for contract address and chain)
python dump_contract.py

# Specify contract address and chain
python dump_contract.py --contract 0xADDRESS --chain bsc

# Paste a full URL (chain is auto-detected)
python dump_contract.py --contract "https://bscscan.com/address/0x..."
```

### Supported Chains

`eth`, `bsc`, `polygon`, `arbitrum`, `optimism`, `avalanche`, `fantom`, `base`

All chains use a single Etherscan API key via the unified V2 API.

## Output

Files are saved to `contracts/<address>/`:

```
contracts/0x.../
├── sources/          # Solidity source files (preserves original directory structure)
├── abi.json          # Contract ABI
├── settings.json     # Compiler version, optimization, EVM version, etc.
├── bytecode.txt      # Deployed bytecode
└── constructor_args.txt  # Constructor arguments (if available)
```
