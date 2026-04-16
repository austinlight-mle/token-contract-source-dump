# Smart Contract Tools

Tools for inspecting and dumping smart contract data from EVM-compatible chains.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Add your keys to `.env`:

```
ETHERSCAN_API=your_api_key_here
BSC_RPC_URL=https://bsc-dataseed.binance.org/
```

---

## Scripts

### `dump_contract.py` — Contract Source Dumper

Dumps verified smart contract source code, ABI, compiler settings, and bytecode from any EVM chain via the Etherscan V2 API.

```bash
python dump_contract.py                                        # interactive prompt
python dump_contract.py --contract 0xADDRESS --chain bsc       # specify address & chain
python dump_contract.py --contract "https://bscscan.com/..."   # auto-detect chain from URL
python dump_contract.py --file contracts.txt                   # batch process from file
```

**Supported chains:** `eth`, `bsc`, `polygon`, `arbitrum`, `optimism`, `avalanche`, `fantom`, `base`

**Output** → `contracts/<address>/` containing `sources/`, `abi.json`, `settings.json`, `bytecode.txt`, `constructor_args.txt`.

---

### `pancake_pair_scan.py` — PancakeSwap Pair Scanner

Scans all PancakeSwap V2 pair contracts (most recent first), filters by USD liquidity, and writes qualifying pairs to `contracts.txt` and `contracts.json`.

- Reads pair addresses from the PancakeSwap V2 Factory (`0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73`) via BSC RPC.
- Fetches liquidity data from the DexScreener API; falls back to on-chain reserves + token prices when a pair isn't indexed.
- Skips pairs below the minimum liquidity threshold (default: $10,000).
- Writes results incrementally so partial results are saved if interrupted.

```bash
python pancake_pair_scan.py                                    # scan all pairs (recent first)
python pancake_pair_scan.py --limit 500                        # scan only the latest 500 pairs
python pancake_pair_scan.py --index 123456                     # scan a single pair at index 123456
python pancake_pair_scan.py --start-index 100000               # start from pair index 100000
python pancake_pair_scan.py --end-index 50000                  # stop at pair index 50000
python pancake_pair_scan.py --start-index 100000 --end-index 99000  # scan a specific range
python pancake_pair_scan.py --min-liq 50000                    # set minimum liquidity to $50,000
```

**Output:**

- `contracts.txt` — one BscScan URL per line for each qualifying pair.
- `contracts.json` — array of objects with `index` (factory pair index), `address`, `price_usd` (total liquidity), `token_a`, `token_b`, and `registered` (pair creation timestamp).
