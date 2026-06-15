"""
Hardcoded stock universe for the /markets stocks tab.
~50 symbols: mega-cap tech + top S&P by mcap + recognizable retail names.
Market caps are approximate (update quarterly).
"""

TOP_STOCKS_UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    "AVGO", "ORCL", "ADBE", "CRM", "NFLX", "AMD",
    # Top S&P by mcap
    "BRK-B", "LLY", "V", "JPM", "WMT", "MA", "XOM", "JNJ",
    "PG", "UNH", "HD", "COST", "ABBV", "BAC", "CVX", "MRK",
    "KO", "PEP", "TMO", "MCD", "PFE", "CSCO", "DIS", "WFC",
    # Recognizable retail names
    "NKE", "INTC", "T", "VZ", "IBM", "BA", "GE", "F", "GM",
    "COIN", "RBLX", "SHOP", "SQ", "PYPL", "UBER", "ABNB",
]

STOCK_NAMES: dict[str, str] = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOGL": "Alphabet",
    "AMZN": "Amazon", "META": "Meta", "TSLA": "Tesla", "AVGO": "Broadcom",
    "ORCL": "Oracle", "ADBE": "Adobe", "CRM": "Salesforce", "NFLX": "Netflix",
    "AMD": "AMD", "BRK-B": "Berkshire Hathaway", "LLY": "Eli Lilly", "V": "Visa",
    "JPM": "JPMorgan", "WMT": "Walmart", "MA": "Mastercard", "XOM": "ExxonMobil",
    "JNJ": "J&J", "PG": "P&G", "UNH": "UnitedHealth", "HD": "Home Depot",
    "COST": "Costco", "ABBV": "AbbVie", "BAC": "BofA", "CVX": "Chevron",
    "MRK": "Merck", "KO": "Coca-Cola", "PEP": "PepsiCo", "TMO": "Thermo Fisher",
    "MCD": "McDonald's", "PFE": "Pfizer", "CSCO": "Cisco", "DIS": "Disney",
    "WFC": "Wells Fargo", "NKE": "Nike", "INTC": "Intel", "T": "AT&T",
    "VZ": "Verizon", "IBM": "IBM", "BA": "Boeing", "GE": "GE Aerospace",
    "F": "Ford", "GM": "GM", "COIN": "Coinbase", "RBLX": "Roblox",
    "SHOP": "Shopify", "SQ": "Block", "PYPL": "PayPal", "UBER": "Uber",
    "ABNB": "Airbnb",
}

# Approximate market cap in USD. Update quarterly.
STOCK_MCAP: dict[str, int] = {
    "AAPL":  3_500_000_000_000,
    "MSFT":  3_200_000_000_000,
    "NVDA":  2_900_000_000_000,
    "GOOGL": 2_100_000_000_000,
    "AMZN":  2_100_000_000_000,
    "META":  1_600_000_000_000,
    "TSLA":  1_000_000_000_000,
    "BRK-B":   950_000_000_000,
    "AVGO":    900_000_000_000,
    "LLY":     800_000_000_000,
    "JPM":     700_000_000_000,
    "WMT":     680_000_000_000,
    "UNH":     490_000_000_000,
    "XOM":     480_000_000_000,
    "V":       550_000_000_000,
    "MA":      440_000_000_000,
    "COST":    400_000_000_000,
    "PG":      390_000_000_000,
    "NFLX":    380_000_000_000,
    "ORCL":    490_000_000_000,
    "CRM":     300_000_000_000,
    "HD":      350_000_000_000,
    "ABBV":    340_000_000_000,
    "BAC":     340_000_000_000,
    "KO":      270_000_000_000,
    "CVX":     285_000_000_000,
    "MRK":     245_000_000_000,
    "AMD":     250_000_000_000,
    "ADBE":    215_000_000_000,
    "PEP":     225_000_000_000,
    "TMO":     198_000_000_000,
    "MCD":     215_000_000_000,
    "CSCO":    200_000_000_000,
    "JNJ":     365_000_000_000,
    "PFE":     148_000_000_000,
    "DIS":     175_000_000_000,
    "WFC":     248_000_000_000,
    "GE":      195_000_000_000,
    "UBER":    160_000_000_000,
    "T":       160_000_000_000,
    "VZ":      155_000_000_000,
    "IBM":     165_000_000_000,
    "ABNB":     85_000_000_000,
    "SHOP":    100_000_000_000,
    "BA":      130_000_000_000,
    "NKE":     110_000_000_000,
    "PYPL":     75_000_000_000,
    "INTC":     95_000_000_000,
    "COIN":     60_000_000_000,
    "SQ":       45_000_000_000,
    "GM":       55_000_000_000,
    "F":        55_000_000_000,
    "RBLX":     25_000_000_000,
}
