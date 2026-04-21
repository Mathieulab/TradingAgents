"""
Custom Trading Agent - Multi-Asset Analysis
Analyzes multiple assets with intraday and swing trading strategies

Features:
- TradingView watchlist integration
- Intraday trading analysis (1-day focus)
- Swing trading analysis (3-10 day focus)
- Previous trade analysis and learning
- Batch processing with rate limiting
- Interactive menu system
- Auto-discovery framework (coming soon)

Author: Mathieu Lascombes
Version: 2.0
"""

# ================================================================================
# IMPORTS
# ================================================================================

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import time
import json
import subprocess
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Load environment variables from .env file
load_dotenv()


# ================================================================================
# CONFIGURATION
# ================================================================================

class TradingConfig:
    """Configuration for trading strategies"""
    
    # TradingView Configuration
    TRADINGVIEW_FILE = Path("watch-list-tradingview.txt")  # Path to exported watchlist
    
    # Results directory
    RESULTS_DIR = Path("results")
    REPORTS_DIR = Path("reports")
    
    # LLM Configuration (using Ollama by default)
    DEFAULT_LLM_PROVIDER = "ollama"
    DEFAULT_BACKEND_URL = "http://localhost:11434/v1"
    DEFAULT_DEEP_THINK_MODEL = "qwen3:8b"
    DEFAULT_QUICK_THINK_MODEL = "qwen3:8b"
    
    # HuggingFace Configuration
    HUGGINGFACE_MODEL_REPO = "TheBloke"  # Popular GGUF model provider
    SUPPORTED_HUGGINGFACE_MODELS = [
        "Llama-3-8B-Instruct-GGUF",
        "Mistral-7B-Instruct-GGUF",
        "Qwen2-7B-Instruct-GGUF",
        "Phi-3-Medium-GGUF",
    ]
    
    # Current runtime configuration (can be changed via menu)
    current_deep_think_model = DEFAULT_DEEP_THINK_MODEL
    current_quick_think_model = DEFAULT_QUICK_THINK_MODEL
    
    # Trading strategy parameters
    INTRADAY_CONFIG = {
        "max_debate_rounds": 2,
        "focus": "short-term momentum and technical signals",
        "timeframe": "1-day"
    }
    
    SWING_CONFIG = {
        "max_debate_rounds": 4,
        "focus": "medium-term trends and fundamental analysis",
        "timeframe": "3-10 days"
    }
    
    # Auto-discovery criteria
    AUTO_ADD_CRITERIA = {
        "min_volume": 1_000_000,  # Minimum daily volume
        "min_market_cap": 1_000_000_000,  # $1B minimum
        "news_mentions_threshold": 5,  # Minimum news mentions
        "sentiment_threshold": 0.6  # Positive sentiment threshold
    }
    
    # Analyst Agent Configuration
    # Available analysts: market, social, news, fundamentals
    DEFAULT_ANALYSTS = ["market", "social", "news", "fundamentals"]
    AVAILABLE_ANALYSTS = ["market", "social", "news", "fundamentals"]
    
    # Research Depth Configuration
    # Shallow: Quick research, few debate and strategy discussion rounds
    # Medium: Middle ground, moderate debate rounds and strategy discussion
    # Deep: Comprehensive research, in-depth debate and strategy discussion
    DEFAULT_RESEARCH_DEPTH = "medium"
    RESEARCH_DEPTH_OPTIONS = ["shallow", "medium", "deep"]
    
    # Current runtime configuration for analysts and research depth
    current_analysts = DEFAULT_ANALYSTS.copy()
    current_research_depth = DEFAULT_RESEARCH_DEPTH
    
    # Platform and Wallet Tracking (for future integration)
    PORTFOLIO_CONFIG_FILE = Path("portfolio_config.json")
    SUPPORTED_STOCK_PLATFORMS = [
        "Degiro", "Interactive Brokers", "TD Ameritrade", "E*TRADE",
        "Fidelity", "Charles Schwab", "Robinhood", "Webull", "Other"
    ]
    SUPPORTED_CRYPTO_PLATFORMS = [
        "Binance", "Coinbase", "Kraken", "Crypto.com", "Bybit",
        "KuCoin", "Bitget", "Hardware Wallet", "Other"
    ]


# ================================================================================
# WATCHLIST MANAGEMENT
# ================================================================================
# Functions for managing and retrieving ticker watchlists from various sources
# including TradingView API, default lists, and auto-discovery.
# ================================================================================

# ─────────────────────────────────────────────────────────────────────────────
# TradingView Integration
# ─────────────────────────────────────────────────────────────────────────────

def parse_tradingview_file(file_path: Path) -> Dict[str, List[str]]:
    """
    Parse TradingView exported watchlist file.
    
    Args:
        file_path: Path to the TradingView watchlist text file
    
    Returns:
        Dictionary with categories as keys and lists of tickers as values
    """
    if not file_path.exists():
        return {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        # Split by commas
        items = content.split(',')
        
        watchlist = {}
        current_category = "General"
        
        for item in items:
            item = item.strip()
            
            # Check if it's a category (starts with ###)
            if item.startswith('###'):
                current_category = item.replace('###', '').strip()
                watchlist[current_category] = []
            elif item and ':' in item:
                # It's a ticker in format EXCHANGE:SYMBOL
                if current_category not in watchlist:
                    watchlist[current_category] = []
                watchlist[current_category].append(item)
        
        return watchlist
    
    except Exception as e:
        print(f"❌ Error parsing TradingView file: {e}")
        return {}


def convert_tradingview_ticker(tv_ticker: str) -> Optional[str]:
    """
    Convert TradingView ticker format to yfinance compatible format.
    
    Examples:
        NYSE:AAPL → AAPL
        NASDAQ:MSFT → MSFT
        BINANCE:BTCUSDT → BTC-USDT
        ^GSPC stays as ^GSPC
    
    Args:
        tv_ticker: TradingView format ticker (EXCHANGE:SYMBOL)
    
    Returns:
        yfinance compatible ticker or None if not supported
    """
    if not tv_ticker or ':' not in tv_ticker:
        return None
    
    try:
        exchange, symbol = tv_ticker.split(':', 1)
        exchange = exchange.upper()
        symbol = symbol.upper()
        
        # Skip futures contracts (ending with !)
        if symbol.endswith('!'):
            return None
        
        # Skip perpetual contracts (.P suffix)
        if symbol.endswith('.P'):
            return None
        
        # Skip complex crypto pairs
        if '+' in symbol or '_' in symbol:
            return None
        
        # Skip economics indicators
        if exchange in ['ECONOMICS', 'CRYPTOCAP']:
            return None
        
        # Handle major US exchanges (NYSE, NASDAQ, AMEX)
        if exchange in ['NYSE', 'NASDAQ', 'AMEX']:
            return symbol
        
        # Handle indices
        if exchange in ['TVC', 'DJ'] and symbol in ['SPX', 'DJI', 'VIX', 'GOLD']:
            return f"^{symbol}" if not symbol.startswith('^') else symbol
        
        # Handle crypto - convert USDT pairs to USD
        if exchange in ['BINANCE', 'KUCOIN', 'BYBIT', 'COINBASE', 'BITSTAMP', 'BITGET']:
            # BTCUSDT → BTC-USD
            if symbol.endswith('USDT'):
                crypto = symbol.replace('USDT', '')
                return f"{crypto}-USD"
            # BTCUSD → BTC-USD
            elif symbol.endswith('USD') and not symbol.endswith('BUSD'):
                crypto = symbol.replace('USD', '')
                return f"{crypto}-USD"
            # Keep as is for direct USD pairs
            elif 'USD' in symbol and not symbol.endswith('USDT'):
                return symbol.replace('USD', '-USD')
        
        # Handle Forex pairs (OANDA, FX)
        if exchange in ['OANDA', 'FX', 'FX_IDC']:
            # EURUSD → EUR-USD, USDJPY → USD-JPY
            if len(symbol) == 6 and symbol.isalpha():
                return f"{symbol[:3]}{symbol[3:]}=X"  # Forex format
            return None
        
        # Handle OTC stocks
        if exchange == 'OTC':
            return symbol
        
        # Skip unsupported exchanges (EURONEXT, LSE, HKEX, etc.)
        # These don't work reliably with yfinance
        if exchange in ['EURONEXT', 'LSE', 'HKEX', 'SIX', 'CAPITALCOM', 
                        'BLACKBULL', 'VANTAGE', 'PEPPERSTONE', 'CME', 'CME_MINI',
                        'COMEX_MINI', 'NYMEX', 'SGX', 'OSE', 'RUS', 'FWB',
                        'HITBTC', 'OKX', 'MEXC', 'GATE', 'PANCAKESWAP', 'UNISWAP3ETH']:
            return None
        
        return None
    
    except Exception:
        return None


def get_tradingview_watchlist() -> List[str]:
    """
    Load watchlist from TradingView exported file.
    Parses the file and converts tickers to yfinance format.
    
    Returns:
        List of ticker symbols compatible with yfinance
    """
    file_path = TradingConfig.TRADINGVIEW_FILE
    
    if not file_path.exists():
        print(f"⚠️  TradingView file not found: {file_path}")
        print("   Using default watchlist instead.")
        return get_default_watchlist()
    
    try:
        print(f"📁 Loading TradingView watchlist from: {file_path.name}")
        
        # Parse the file
        watchlist_by_category = parse_tradingview_file(file_path)
        
        if not watchlist_by_category:
            print("⚠️  No tickers found in TradingView file")
            return get_default_watchlist()
        
        # Convert all tickers
        converted_tickers = []
        skipped_count = 0
        
        for category, tv_tickers in watchlist_by_category.items():
            for tv_ticker in tv_tickers:
                yf_ticker = convert_tradingview_ticker(tv_ticker)
                if yf_ticker and yf_ticker not in converted_tickers:
                    converted_tickers.append(yf_ticker)
                else:
                    skipped_count += 1
        
        print(f"✅ Loaded {len(converted_tickers)} tickers from TradingView")
        print(f"ℹ️  Skipped {skipped_count} unsupported tickers")
        
        if converted_tickers:
            # Show sample
            sample = converted_tickers[:10]
            print(f"📊 Sample tickers: {', '.join(sample)}")
            if len(converted_tickers) > 10:
                print(f"   ... and {len(converted_tickers) - 10} more")
            return converted_tickers
        else:
            print("⚠️  No compatible tickers found")
            return get_default_watchlist()
        
    except Exception as e:
        print(f"❌ Error loading TradingView watchlist: {e}")
        print("   Using default watchlist instead.")
        return get_default_watchlist()


# ─────────────────────────────────────────────────────────────────────────────
# Default Watchlist
# ─────────────────────────────────────────────────────────────────────────────

def get_default_watchlist() -> List[str]:
    """Default watchlist if TradingView API is not available"""
    return [
        # Indices
        "^GSPC",    # S&P 500
        "^DJI",     # Dow Jones
        "^IXIC",    # NASDAQ
        
        # Crypto
        "BTC-USD",  # Bitcoin
        "ETH-USD",  # Ethereum
        
        # Top Stocks
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
        "TSLA", "META", "JPM", "V", "WMT"
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Discovery (Placeholder)
# ─────────────────────────────────────────────────────────────────────────────

def auto_discover_tickers() -> List[str]:
    """
    Auto-discover interesting tickers based on:
    - Recent news mentions
    - High volume movements
    - User-defined criteria
    
    TODO: Implement full auto-discovery logic
    This is a placeholder for future implementation.
    """
    discovered = []
    
    # Placeholder: Could integrate with:
    # - News APIs (Alpha Vantage, NewsAPI)
    # - Social media sentiment
    # - Volume spike detection
    # - Technical breakout patterns
    
    print("ℹ️  Auto-discovery feature: Coming soon")
    return discovered


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist Utilities
# ─────────────────────────────────────────────────────────────────────────────

def merge_watchlists(*watchlists: List[str]) -> List[str]:
    """Merge multiple watchlists and remove duplicates"""
    combined = []
    seen = set()
    
    for watchlist in watchlists:
        for ticker in watchlist:
            if ticker and ticker not in seen:
                combined.append(ticker)
                seen.add(ticker)
    
    return combined


# ================================================================================
# PORTFOLIO & PLATFORM TRACKING
# ================================================================================
# Functions for tracking user's trading platforms and wallet addresses.
# This is prepared for future integration without affecting current functionality.
# ================================================================================

def load_portfolio_config() -> Dict[str, any]:
    """
    Load portfolio configuration from file.
    
    Returns:
        Dictionary with platform and wallet information
    """
    config_file = TradingConfig.PORTFOLIO_CONFIG_FILE
    
    if not config_file.exists():
        return {
            "stock_platforms": {},
            "crypto_wallets": {},
            "last_updated": None
        }
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Error loading portfolio config: {e}")
        return {
            "stock_platforms": {},
            "crypto_wallets": {},
            "last_updated": None
        }


def save_portfolio_config(config: Dict[str, any]):
    """
    Save portfolio configuration to file.
    
    Args:
        config: Dictionary with platform and wallet information
    """
    config_file = TradingConfig.PORTFOLIO_CONFIG_FILE
    config["last_updated"] = datetime.now().isoformat()
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        print(f"💾 Portfolio configuration saved")
    except Exception as e:
        print(f"❌ Error saving portfolio config: {e}")


def prompt_stock_platform(ticker: str) -> Optional[Dict[str, str]]:
    """
    Ask user for stock trading platform for a specific ticker.
    
    Args:
        ticker: Stock ticker symbol
    
    Returns:
        Dictionary with platform info or None if skipped
    """
    print(f"\n📊 Stock Platform Setup for {ticker}")
    print(f"Do you hold {ticker} on a trading platform?")
    
    response = input("Track this position? (y/n): ").strip().lower()
    
    if response != 'y':
        return None
    
    print(f"\nSelect your platform:")
    for i, platform in enumerate(TradingConfig.SUPPORTED_STOCK_PLATFORMS, 1):
        print(f"  {i}. {platform}")
    
    choice = input(f"\nSelect platform (1-{len(TradingConfig.SUPPORTED_STOCK_PLATFORMS)}): ").strip()
    
    if choice.isdigit() and 1 <= int(choice) <= len(TradingConfig.SUPPORTED_STOCK_PLATFORMS):
        platform = TradingConfig.SUPPORTED_STOCK_PLATFORMS[int(choice) - 1]
        
        if platform == "Other":
            platform = input("Enter platform name: ").strip() or "Other"
        
        account_id = input("Account ID/Username (optional, press Enter to skip): ").strip()
        
        return {
            "platform": platform,
            "account_id": account_id if account_id else "Not specified",
            "ticker": ticker,
            "type": "stock",
            "added_date": datetime.now().isoformat()
        }
    
    return None


def prompt_crypto_wallet(ticker: str) -> Optional[Dict[str, str]]:
    """
    Ask user for crypto wallet/exchange for a specific ticker.
    
    Args:
        ticker: Crypto ticker symbol (e.g., BTC-USD)
    
    Returns:
        Dictionary with wallet/platform info or None if skipped
    """
    print(f"\n💰 Crypto Platform/Wallet Setup for {ticker}")
    print(f"Do you hold {ticker} on an exchange or wallet?")
    
    response = input("Track this position? (y/n): ").strip().lower()
    
    if response != 'y':
        return None
    
    print(f"\nSelect your platform/wallet:")
    for i, platform in enumerate(TradingConfig.SUPPORTED_CRYPTO_PLATFORMS, 1):
        print(f"  {i}. {platform}")
    
    choice = input(f"\nSelect platform (1-{len(TradingConfig.SUPPORTED_CRYPTO_PLATFORMS)}): ").strip()
    
    if choice.isdigit() and 1 <= int(choice) <= len(TradingConfig.SUPPORTED_CRYPTO_PLATFORMS):
        platform = TradingConfig.SUPPORTED_CRYPTO_PLATFORMS[int(choice) - 1]
        
        if platform == "Other":
            platform = input("Enter platform/wallet name: ").strip() or "Other"
        
        # Ask for wallet address if it's a wallet, exchange info if exchange
        if "Wallet" in platform:
            wallet_address = input("Wallet address (optional, press Enter to skip): ").strip()
            identifier = wallet_address if wallet_address else "Not specified"
        else:
            account_id = input("Account ID/Email (optional, press Enter to skip): ").strip()
            identifier = account_id if account_id else "Not specified"
        
        return {
            "platform": platform,
            "identifier": identifier,
            "ticker": ticker,
            "type": "crypto",
            "added_date": datetime.now().isoformat()
        }
    
    return None


def setup_portfolio_tracking(ticker: str, force_prompt: bool = False):
    """
    Setup portfolio tracking for a ticker (stocks or crypto).
    Checks if already configured and prompts user if needed.
    
    Args:
        ticker: Ticker symbol
        force_prompt: Force prompt even if already configured
    """
    # Load existing config
    config = load_portfolio_config()
    
    # Determine if it's crypto or stock
    is_crypto = "-USD" in ticker or ticker in ["BTC-USD", "ETH-USD", "USDT-USD"]
    
    # Check if already configured
    if not force_prompt:
        if is_crypto and ticker in config.get("crypto_wallets", {}):
            print(f"✅ {ticker} already tracked on {config['crypto_wallets'][ticker]['platform']}")
            return
        elif not is_crypto and ticker in config.get("stock_platforms", {}):
            print(f"✅ {ticker} already tracked on {config['stock_platforms'][ticker]['platform']}")
            return
    
    # Prompt for platform/wallet info
    if is_crypto:
        info = prompt_crypto_wallet(ticker)
        if info:
            config.setdefault("crypto_wallets", {})[ticker] = info
            save_portfolio_config(config)
    else:
        info = prompt_stock_platform(ticker)
        if info:
            config.setdefault("stock_platforms", {})[ticker] = info
            save_portfolio_config(config)


def display_portfolio_tracking():
    """
    Display current portfolio tracking configuration.
    Shows all tracked platforms and wallets.
    """
    config = load_portfolio_config()
    
    print(f"\n{'='*80}")
    print("📊 PORTFOLIO TRACKING CONFIGURATION".center(80))
    print(f"{'='*80}\n")
    
    # Display stock platforms
    stock_platforms = config.get("stock_platforms", {})
    if stock_platforms:
        print("📈 Stock Trading Platforms:\n")
        for ticker, info in stock_platforms.items():
            print(f"  • {ticker:10} → {info['platform']}")
            if info.get('account_id') and info['account_id'] != "Not specified":
                print(f"    Account: {info['account_id']}")
        print()
    else:
        print("📈 Stock Trading Platforms: None configured\n")
    
    # Display crypto wallets
    crypto_wallets = config.get("crypto_wallets", {})
    if crypto_wallets:
        print("💰 Crypto Platforms/Wallets:\n")
        for ticker, info in crypto_wallets.items():
            print(f"  • {ticker:10} → {info['platform']}")
            if info.get('identifier') and info['identifier'] != "Not specified":
                # Mask wallet addresses for security (show first 6 and last 4 chars)
                identifier = info['identifier']
                if len(identifier) > 15:
                    masked = f"{identifier[:6]}...{identifier[-4:]}"
                    print(f"    Address: {masked}")
                else:
                    print(f"    Account: {identifier}")
        print()
    else:
        print("💰 Crypto Platforms/Wallets: None configured\n")
    
    # Display last updated
    if config.get("last_updated"):
        print(f"Last updated: {config['last_updated']}")
    
    print(f"\n{'='*80}\n")


def manage_portfolio_tracking():
    """
    Interactive menu for managing portfolio tracking.
    Allows users to add, view, or remove platform/wallet configurations.
    """
    print_header("PORTFOLIO TRACKING MANAGEMENT")
    
    print("This feature allows you to track which platforms/wallets you use for each asset.")
    print("This is useful for portfolio management and future integrations.\n")
    
    print("Options:")
    print("1. View current configuration")
    print("2. Add/Update stock platform")
    print("3. Add/Update crypto wallet/platform")
    print("4. Remove tracking for a ticker")
    print("5. Clear all tracking data")
    print("0. Back to main menu")
    
    choice = input("\nSelect option: ").strip()
    
    if choice == "1":
        display_portfolio_tracking()
    
    elif choice == "2":
        ticker = input("\nEnter stock ticker: ").strip().upper()
        if ticker:
            setup_portfolio_tracking(ticker, force_prompt=True)
    
    elif choice == "3":
        ticker = input("\nEnter crypto ticker (e.g., BTC-USD): ").strip().upper()
        if ticker:
            setup_portfolio_tracking(ticker, force_prompt=True)
    
    elif choice == "4":
        ticker = input("\nEnter ticker to remove: ").strip().upper()
        if ticker:
            config = load_portfolio_config()
            removed = False
            
            if ticker in config.get("stock_platforms", {}):
                del config["stock_platforms"][ticker]
                removed = True
            
            if ticker in config.get("crypto_wallets", {}):
                del config["crypto_wallets"][ticker]
                removed = True
            
            if removed:
                save_portfolio_config(config)
                print(f"✅ Removed tracking for {ticker}")
            else:
                print(f"ℹ️  {ticker} not found in tracking configuration")
    
    elif choice == "5":
        confirm = input("\n⚠️  Clear all portfolio tracking data? (yes/no): ").strip().lower()
        if confirm == "yes":
            config = {
                "stock_platforms": {},
                "crypto_wallets": {},
                "last_updated": None
            }
            save_portfolio_config(config)
            print("✅ All portfolio tracking data cleared")
    
    elif choice != "0":
        print("❌ Invalid option")


# ================================================================================
# MODEL MANAGEMENT
# ================================================================================
# Functions for checking, downloading, and managing LLM models from Ollama and HuggingFace.
# ================================================================================

# ─────────────────────────────────────────────────────────────────────────────
# Ollama Model Management
# ─────────────────────────────────────────────────────────────────────────────

def check_ollama_running() -> bool:
    """Check if Ollama service is running"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        return response.status_code == 200
    except:
        return False


def list_ollama_models() -> List[str]:
    """List all locally available Ollama models"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        return []
    except Exception as e:
        print(f"❌ Error listing Ollama models: {e}")
        return []


def check_model_exists(model_name: str) -> bool:
    """Check if a specific model exists in Ollama"""
    models = list_ollama_models()
    # Check both exact match and with :latest tag
    return model_name in models or f"{model_name}:latest" in models or any(m.startswith(f"{model_name}:") for m in models)


def pull_ollama_model(model_name: str) -> bool:
    """
    Pull a model from Ollama registry.
    
    Args:
        model_name: Name of the model to pull (e.g., "llama3:8b")
    
    Returns:
        True if successful, False otherwise
    """
    print(f"\n🔽 Downloading model: {model_name}")
    print("This may take a few minutes depending on model size...\n")
    
    try:
        # Use subprocess to show progress
        result = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=False,
            text=True
        )
        
        if result.returncode == 0:
            print(f"\n✅ Successfully downloaded {model_name}")
            return True
        else:
            print(f"\n❌ Failed to download {model_name}")
            return False
            
    except FileNotFoundError:
        print("❌ Error: Ollama CLI not found. Please install Ollama first.")
        print("   Visit: https://ollama.ai")
        return False
    except Exception as e:
        print(f"❌ Error downloading model: {e}")
        return False


def ensure_model_available(model_name: str) -> bool:
    """
    Ensure a model is available, download if necessary.
    
    Args:
        model_name: Name of the model
    
    Returns:
        True if model is available, False otherwise
    """
    if check_model_exists(model_name):
        print(f"✅ Model '{model_name}' is already available")
        return True
    
    print(f"⚠️  Model '{model_name}' not found locally")
    
    # Ask user if they want to download
    choice = input(f"Download '{model_name}' now? (y/n): ").strip().lower()
    
    if choice == 'y':
        return pull_ollama_model(model_name)
    else:
        print("⏭️  Skipping download")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# HuggingFace Integration
# ─────────────────────────────────────────────────────────────────────────────

def search_huggingface_models(query: str = "GGUF") -> List[Dict[str, str]]:
    """
    Search for GGUF models on HuggingFace.
    
    Args:
        query: Search query (default: "GGUF")
    
    Returns:
        List of model information dictionaries
    """
    print(f"🔍 Searching HuggingFace for '{query}' models...\n")
    
    # Popular GGUF model providers and their models
    popular_models = [
        {"name": "llama3:8b", "repo": "meta-llama/Meta-Llama-3-8B", "description": "Llama 3 8B - Meta's powerful language model"},
        {"name": "mistral:7b", "repo": "mistralai/Mistral-7B-v0.1", "description": "Mistral 7B - High performance model"},
        {"name": "qwen2:7b", "repo": "Qwen/Qwen2-7B", "description": "Qwen 2 7B - Alibaba's multilingual model"},
        {"name": "phi3:medium", "repo": "microsoft/Phi-3-medium", "description": "Phi-3 Medium - Microsoft's efficient model"},
        {"name": "gemma2:9b", "repo": "google/gemma-2-9b", "description": "Gemma 2 9B - Google's open model"},
        {"name": "deepseek-coder:6.7b", "repo": "deepseek-ai/deepseek-coder-6.7b", "description": "DeepSeek Coder - Specialized for code"},
    ]
    
    return popular_models


def download_huggingface_model_to_ollama(model_name: str, repo_id: str) -> bool:
    """
    Download a HuggingFace GGUF model and import to Ollama.
    
    Note: This requires the model to be available in Ollama's registry.
    For custom HuggingFace models, users need to manually create a Modelfile.
    
    Args:
        model_name: Name to use in Ollama
        repo_id: HuggingFace repository ID or model name
    
    Returns:
        True if successful, False otherwise
    """
    print(f"\n📦 Preparing to download model...")
    print(f"   Model: {model_name}")
    if repo_id != model_name:
        print(f"   Source: {repo_id}")
    print()
    
    # Try to pull from Ollama registry first
    print("🔍 Checking Ollama registry...")
    if pull_ollama_model(model_name):
        return True
    
    print("\n💡 Model not available in Ollama registry.")
    print("\n📋 Options for custom HuggingFace GGUF models:\n")
    print("Option 1 - Automatic Import (if you have the .gguf file):")
    print("  1. Download GGUF file from HuggingFace")
    print(f"     URL: https://huggingface.co/{repo_id}")
    print("  2. Create a Modelfile in the same directory:")
    print("     ---")
    print("     FROM ./model.gguf")
    print("     PARAMETER temperature 0.7")
    print("     PARAMETER top_p 0.9")
    print("     ---")
    print(f"  3. Run: ollama create {model_name} -f Modelfile")
    print()
    print("Option 2 - Use Ollama library:")
    print("  • Check https://ollama.com/library for available models")
    print("  • Many HuggingFace models are already available")
    print("  • Format: model_name:size (e.g., llama3:8b)")
    print()
    print("Option 3 - Community models:")
    print("  • Browse https://ollama.com/search")
    print("  • Many quantized GGUF models ready to use")
    print()
    print("📚 Complete guide: https://github.com/ollama/ollama/blob/main/docs/import.md")
    print()
    
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Model Selection Interface
# ─────────────────────────────────────────────────────────────────────────────

def display_available_models():
    """Display all available Ollama models with details"""
    print(f"\n{'─'*80}")
    print("📚 AVAILABLE MODELS")
    print(f"{'─'*80}\n")
    
    if not check_ollama_running():
        print("❌ Ollama is not running!")
        print("   Please start Ollama first: 'ollama serve'")
        return
    
    models = list_ollama_models()
    
    if not models:
        print("ℹ️  No models installed yet.")
        print("\n💡 You can download models from:")
        print("   • Ollama library: https://ollama.com/library")
        print("   • Use menu option 3 in Model Configuration to download")
    else:
        print(f"Found {len(models)} installed model(s):\n")
        for i, model in enumerate(models, 1):
            # Check if it's a currently selected model
            marker = ""
            if model == TradingConfig.current_deep_think_model:
                marker = " [DEEP THINK] ✨"
            elif model == TradingConfig.current_quick_think_model:
                marker = " [QUICK THINK] ⚡"
            print(f"  {i}. {model}{marker}")
        
        print(f"\n📊 Currently Active:")
        print(f"   Deep Think: {TradingConfig.current_deep_think_model}")
        print(f"   Quick Think: {TradingConfig.current_quick_think_model}")
    
    print(f"\n{'─'*80}")


def prompt_model_selection_on_startup() -> bool:
    """
    Prompt user to select models on startup.
    
    Returns:
        True if models are configured, False if user wants to skip
    """
    print(f"\n{'='*80}")
    print("🤖 MODEL CONFIGURATION".center(80))
    print(f"{'='*80}\n")
    
    # Check Ollama status
    if not check_ollama_running():
        print("❌ Ollama is not running!")
        print("\n⚠️  Please start Ollama to use this trading agent:")
        print("   1. Open a new terminal")
        print("   2. Run: ollama serve")
        print("\nOr download Ollama: https://ollama.ai")
        print("\nPress Enter to exit...")
        input()
        return False
    
    print("✅ Ollama is running\n")
    
    # Show current default models
    print(f"Default Configuration:")
    print(f"  • Deep Think Model: {TradingConfig.DEFAULT_DEEP_THINK_MODEL}")
    print(f"  • Quick Think Model: {TradingConfig.DEFAULT_QUICK_THINK_MODEL}\n")
    
    # Check if defaults exist
    deep_exists = check_model_exists(TradingConfig.DEFAULT_DEEP_THINK_MODEL)
    quick_exists = check_model_exists(TradingConfig.DEFAULT_QUICK_THINK_MODEL)
    
    if deep_exists and quick_exists:
        print("✅ Default models are available\n")
        use_default = input("Use default models? (Y/n): ").strip().lower()
        
        if use_default in ['', 'y', 'yes']:
            print("\n✅ Using default models\n")
            return True
    else:
        print("⚠️  Default models not found locally\n")
    
    # Show available models summary
    available_models = list_ollama_models()
    if available_models:
        print(f"{'─'*80}")
        print(f"📚 INSTALLED MODELS ({len(available_models)} available)")
        print(f"{'─'*80}")
        # Show up to 8 models
        display_count = min(8, len(available_models))
        for i, model in enumerate(available_models[:display_count], 1):
            print(f"  • {model}")
        if len(available_models) > 8:
            print(f"  ... and {len(available_models) - 8} more")
        print()
    
    # Offer model selection
    print(f"{'─'*80}")
    print("SELECT MODELS".center(80))
    print(f"{'─'*80}\n")
    
    print("Choose an option:")
    print("1. 🔽 Download default models (recommended)")
    print("2. 🎨 Select from available models")
    print("3. 📋 View popular models")
    print("4. 🌐 Enter custom model from HuggingFace/Ollama")
    print("0. ⏭️  Skip (use defaults anyway)")
    
    choice = input("\nYour choice: ").strip()
    
    if choice == "1":
        # Download defaults
        print(f"\n{'─'*80}")
        print("DOWNLOADING DEFAULT MODELS")
        print(f"{'─'*80}\n")
        
        success = True
        
        if not deep_exists:
            print(f"Downloading Deep Think Model: {TradingConfig.DEFAULT_DEEP_THINK_MODEL}")
            deep_success = pull_ollama_model(TradingConfig.DEFAULT_DEEP_THINK_MODEL)
            success = success and deep_success
        
        if not quick_exists and TradingConfig.DEFAULT_QUICK_THINK_MODEL != TradingConfig.DEFAULT_DEEP_THINK_MODEL:
            print(f"\nDownloading Quick Think Model: {TradingConfig.DEFAULT_QUICK_THINK_MODEL}")
            quick_success = pull_ollama_model(TradingConfig.DEFAULT_QUICK_THINK_MODEL)
            success = success and quick_success
        
        if success:
            print("\n✅ Default models ready!")
        else:
            print("\n⚠️  Some downloads failed. You can try again from the Model Configuration menu.")
        
        return True
    
    elif choice == "2":
        # Custom selection
        print(f"\n{'─'*80}")
        print("CUSTOM MODEL SELECTION")
        print(f"{'─'*80}\n")
        
        # Show what's available first
        available_models = list_ollama_models()
        if available_models:
            print(f"Current installed models: {len(available_models)}")
            print(f"  {', '.join(available_models[:5])}")
            if len(available_models) > 5:
                print(f"  ... and {len(available_models) - 5} more")
            print()
        else:
            print("⚠️  No models currently installed.")
            print("   You'll need to download a model.\n")
        
        # Select Deep Think Model
        print("🧠 Select Deep Think Model (for complex analysis):")
        deep_model = select_model_interactive()
        
        if deep_model:
            if check_model_exists(deep_model) or ensure_model_available(deep_model):
                TradingConfig.current_deep_think_model = deep_model
                print(f"\n✅ Deep Think Model: {deep_model}")
            else:
                print("\n⚠️  Using default deep think model")
        
        # Select Quick Think Model
        print("\n⚡ Select Quick Think Model (for fast decisions):")
        same = input("Use same model for quick thinking? (Y/n): ").strip().lower()
        
        if same in ['', 'y', 'yes']:
            TradingConfig.current_quick_think_model = TradingConfig.current_deep_think_model
            print(f"✅ Quick Think Model: {TradingConfig.current_quick_think_model}")
        else:
            quick_model = select_model_interactive()
            if quick_model:
                if check_model_exists(quick_model) or ensure_model_available(quick_model):
                    TradingConfig.current_quick_think_model = quick_model
                    print(f"\n✅ Quick Think Model: {quick_model}")
                else:
                    print("\n⚠️  Using default quick think model")
        
        print(f"\n{'─'*80}")
        print(f"✅ Model configuration complete!")
        print(f"   Deep Think: {TradingConfig.current_deep_think_model}")
        print(f"   Quick Think: {TradingConfig.current_quick_think_model}")
        print(f"{'─'*80}\n")
        
        return True
    
    elif choice == "3":
        # Show popular models
        print(f"\n{'─'*80}")
        print("POPULAR MODELS")
        print(f"{'─'*80}\n")
        
        print("Available via Ollama:\n")
        print("  1. llama3:8b      - Meta Llama 3 (8B) - Versatile & powerful")
        print("  2. mistral:7b     - Mistral 7B - High performance")
        print("  3. qwen2:7b       - Qwen 2 7B - Multilingual support")
        print("  4. phi3:medium    - Microsoft Phi-3 - Efficient")
        print("  5. gemma2:9b      - Google Gemma 2 - Open model")
        print("  6. deepseek-coder:6.7b - DeepSeek - Code specialist")
        print()
        
        model_map = {
            "1": "llama3:8b",
            "2": "mistral:7b",
            "3": "qwen2:7b",
            "4": "phi3:medium",
            "5": "gemma2:9b",
            "6": "deepseek-coder:6.7b"
        }
        
        selection = input("Select model number to download (1-6) or 0 to go back: ").strip()
        
        if selection in model_map:
            model_name = model_map[selection]
            print(f"\n📦 Downloading {model_name}...")
            
            if pull_ollama_model(model_name):
                # Set as both models
                TradingConfig.current_deep_think_model = model_name
                TradingConfig.current_quick_think_model = model_name
                print(f"\n✅ Model configured: {model_name}")
                return True
        
        # Go back to main prompt
        return prompt_model_selection_on_startup()
    
    elif choice == "4":
        # Custom model entry
        print(f"\n{'─'*80}")
        print("CUSTOM MODEL ENTRY")
        print(f"{'─'*80}\n")
        
        print("You can enter model names from:")
        print("  • Ollama registry (most common)")
        print("  • Any GGUF model available via Ollama")
        print()
        print("Popular model formats on HuggingFace:")
        print("  - Models ending in -GGUF (ready for Ollama)")
        print("  - TheBloke's quantized models")
        print("  - Any model in Ollama format")
        print()
        print("Examples:")
        print("  • llama3:8b (from Ollama)")
        print("  • mistral:7b-instruct-v0.2-q4_K_M (specific quantization)")
        print("  • codellama:13b-python")
        print("  • wizard-vicuna-uncensored:30b")
        print()
        
        # Deep Think Model
        print("🧠 Enter Deep Think Model name:")
        deep_model = input("Model name: ").strip()
        
        if deep_model:
            print(f"\n📦 Downloading {deep_model}...")
            if pull_ollama_model(deep_model):
                TradingConfig.current_deep_think_model = deep_model
                print(f"✅ Deep Think Model set to: {deep_model}")
            else:
                print("\n⚠️  Download failed. Using default deep think model.")
                print("\n💡 For custom HuggingFace GGUF models:")
                print("   1. Download .gguf file from HuggingFace")
                print("   2. Create Modelfile: FROM ./path/to/model.gguf")
                print("   3. Import: ollama create mymodel -f Modelfile")
                print("   4. Docs: https://github.com/ollama/ollama/blob/main/docs/import.md")
        
        # Quick Think Model
        print("\n⚡ Enter Quick Think Model name:")
        print("(Press Enter to use same as Deep Think)")
        quick_model = input("Model name: ").strip()
        
        if not quick_model:
            TradingConfig.current_quick_think_model = TradingConfig.current_deep_think_model
            print(f"✅ Quick Think Model: {TradingConfig.current_quick_think_model}")
        elif quick_model:
            print(f"\n📦 Downloading {quick_model}...")
            if pull_ollama_model(quick_model):
                TradingConfig.current_quick_think_model = quick_model
                print(f"✅ Quick Think Model set to: {quick_model}")
            else:
                print("\n⚠️  Download failed. Using same as Deep Think model.")
                TradingConfig.current_quick_think_model = TradingConfig.current_deep_think_model
        
        print(f"\n{'─'*80}")
        print("✅ Custom model configuration complete!")
        print(f"   Deep Think: {TradingConfig.current_deep_think_model}")
        print(f"   Quick Think: {TradingConfig.current_quick_think_model}")
        print(f"{'─'*80}\n")
        
        return True
    
    else:
        # Skip
        print("\n⏭️  Skipping model configuration")
        print("   You can configure models later from menu option 8\n")
        return True


def select_model_interactive() -> Optional[str]:
    """
    Interactive model selection.
    
    Returns:
        Selected model name or None if cancelled
    """
    if not check_ollama_running():
        print("❌ Ollama is not running!")
        print("   Please start Ollama first: 'ollama serve'")
        return None
    
    models = list_ollama_models()
    
    if models:
        print(f"\n{'-'*60}")
        print(f"📚 AVAILABLE MODELS ({len(models)} installed)")
        print(f"{'-'*60}")
        for i, model in enumerate(models, 1):
            print(f"  {i}. ✅ {model}")
        print(f"{'-'*60}\n")
    else:
        print("\nℹ️  No models installed yet. Please download one.\n")
    
    print("Additional Options:")
    print(f"  {len(models) + 1}. 🔽 Download new model")
    print(f"  {len(models) + 2}. 🔍 Browse HuggingFace models")
    print(f"  {len(models) + 3}. 🎨 Enter custom model name")
    print("  0. Cancel")
    
    choice = input("\nSelect option: ").strip()
    
    if choice == "0":
        return None
    elif choice.isdigit() and 1 <= int(choice) <= len(models):
        return models[int(choice) - 1]
    elif choice == str(len(models) + 1):
        # Download new model
        model_name = input("\nEnter model name (e.g., llama3:8b, mistral:7b): ").strip()
        if model_name and pull_ollama_model(model_name):
            return model_name
        return None
    elif choice == str(len(models) + 2):
        # Browse HuggingFace
        hf_models = search_huggingface_models()
        print("\n🤗 Popular HuggingFace Models (via Ollama):\n")
        for i, model in enumerate(hf_models, 1):
            print(f"  {i}. {model['name']}")
            print(f"     {model['description']}")
            print()
        
        print(f"  {len(hf_models) + 1}. 🎨 Enter custom HuggingFace model")
        print("  0. Cancel")
        
        choice = input(f"\nSelect option (1-{len(hf_models) + 1}): ").strip()
        
        if choice == "0":
            return None
        elif choice.isdigit() and 1 <= int(choice) <= len(hf_models):
            selected = hf_models[int(choice) - 1]
            if download_huggingface_model_to_ollama(selected["name"], selected["repo"]):
                return selected["name"]
            return None
        elif choice == str(len(hf_models) + 1):
            # Custom HuggingFace model
            print("\n🎨 Custom HuggingFace Model\n")
            print("You can enter either:")
            print("  1. A model name from Ollama registry (e.g., 'llama3:8b')")
            print("  2. A HuggingFace repository (e.g., 'TheBloke/Llama-2-7B-GGUF')")
            print()
            
            model_input = input("Enter model name or HuggingFace repo: ").strip()
            
            if not model_input:
                print("❌ No model specified")
                return None
            
            # Try to download from HuggingFace
            if download_huggingface_model_to_ollama(model_input, model_input):
                return model_input
            return None
        else:
            print("❌ Invalid choice")
            return None
    elif choice == str(len(models) + 3):
        # Custom model name entry
        print("\n🎨 Custom Model Entry\n")
        print("Enter a model name to download from:")
        print("  • Ollama registry (e.g., llama3:8b, mistral:7b)")
        print("  • HuggingFace via Ollama (e.g., any GGUF model available)")
        print()
        print("Examples:")
        print("  - llama3:8b")
        print("  - mistral:latest")
        print("  - codellama:13b")
        print("  - wizard-vicuna-uncensored:latest")
        print()
        
        model_name = input("Enter model name: ").strip()
        
        if not model_name:
            print("❌ No model name provided")
            return None
        
        print(f"\n📦 Attempting to download: {model_name}")
        
        if pull_ollama_model(model_name):
            return model_name
        else:
            print("\n⚠️  Model download failed.")
            print("\nFor custom HuggingFace GGUF models:")
            print("1. Download GGUF file from HuggingFace")
            print("2. Create a Modelfile:")
            print("   FROM ./path/to/model.gguf")
            print("3. Import: ollama create mymodel -f Modelfile")
            print("\nDocs: https://github.com/ollama/ollama/blob/main/docs/import.md")
            return None
    else:
        print("❌ Invalid choice")
        return None


def create_ollama_config() -> dict:
    """
    Create configuration using Ollama LLM provider.
    
    Returns:
        Configuration dictionary with Ollama settings
    """
    from tradingagents.default_config import DEFAULT_CONFIG
    
    config = DEFAULT_CONFIG.copy()
    
    # Override with Ollama settings (use current runtime config)
    config["llm_provider"] = TradingConfig.DEFAULT_LLM_PROVIDER
    config["backend_url"] = TradingConfig.DEFAULT_BACKEND_URL
    config["deep_think_llm"] = TradingConfig.current_deep_think_model
    config["quick_think_llm"] = TradingConfig.current_quick_think_model
    
    # Set active analysts
    config["analysts"] = TradingConfig.current_analysts.copy()
    
    # Set research depth
    config["research_depth"] = TradingConfig.current_research_depth
    
    return config


def get_watchlist_by_category(category_filter: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Get TradingView watchlist organized by categories.
    
    Args:
        category_filter: Optional list of category names to include.
                        If None, returns all categories.
    
    Returns:
        Dictionary with categories and their converted tickers
    """
    file_path = TradingConfig.TRADINGVIEW_FILE
    
    if not file_path.exists():
        return {"Default": get_default_watchlist()}
    
    try:
        watchlist_by_category = parse_tradingview_file(file_path)
        
        result = {}
        for category, tv_tickers in watchlist_by_category.items():
            # Apply filter if specified
            if category_filter and category not in category_filter:
                continue
            
            converted = []
            for tv_ticker in tv_tickers:
                yf_ticker = convert_tradingview_ticker(tv_ticker)
                if yf_ticker:
                    converted.append(yf_ticker)
            
            if converted:
                result[category] = converted
        
        return result if result else {"Default": get_default_watchlist()}
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"Default": get_default_watchlist()}


# ================================================================================
# REPORT ANALYSIS
# ================================================================================
# Functions for analyzing previous trading reports and extracting insights.
# Reports are stored in results/{TICKER}/{DATE}/reports/ directory.
# ================================================================================

# ─────────────────────────────────────────────────────────────────────────────
# Report Retrieval
# ─────────────────────────────────────────────────────────────────────────────

def get_latest_report(ticker: str) -> Optional[Dict[str, str]]:
    """
    Get the most recent trading report for a ticker.
    Returns a dictionary with report contents.
    """
    ticker_dir = TradingConfig.RESULTS_DIR / ticker
    
    if not ticker_dir.exists():
        return None
    
    # Find the most recent date folder
    date_folders = sorted([d for d in ticker_dir.iterdir() if d.is_dir()], reverse=True)
    
    if not date_folders:
        return None
    
    latest_date = date_folders[0]
    reports_dir = latest_date / "reports"
    
    if not reports_dir.exists():
        return None
    
    report_data = {}
    report_files = [
        "final_trade_decision.md",
        "investment_plan.md",
        "trader_investment_plan.md",
        "market_report.md",
        "news_report.md",
        "sentiment_report.md",
        "fundamentals_report.md"
    ]
    
    for report_file in report_files:
        report_path = reports_dir / report_file
        if report_path.exists():
            with open(report_path, 'r', encoding='utf-8') as f:
                report_data[report_file.replace('.md', '')] = f.read()
    
    return report_data if report_data else None


# ─────────────────────────────────────────────────────────────────────────────
# Trade Analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_previous_trade(ticker: str) -> Dict[str, any]:
    """
    Analyze the previous trade decision and outcome.
    Extracts key insights from the last trading report.
    """
    report = get_latest_report(ticker)
    
    if not report:
        return {
            "has_previous_trade": False,
            "message": "No previous trade found"
        }
    
    # Extract decision from final trade decision
    decision_text = report.get('final_trade_decision', '')
    
    # Simple parsing to extract verdict
    verdict = "UNKNOWN"
    if "BUY" in decision_text.upper():
        verdict = "BUY"
    elif "SELL" in decision_text.upper():
        verdict = "SELL"
    elif "HOLD" in decision_text.upper():
        verdict = "HOLD"
    
    analysis = {
        "has_previous_trade": True,
        "verdict": verdict,
        "decision_summary": decision_text[:500] if decision_text else "No summary available",
        "investment_plan_summary": report.get('investment_plan', '')[:300],
        "market_conditions": report.get('market_report', '')[:300],
    }
    
    return analysis


# ─────────────────────────────────────────────────────────────────────────────
# Report Display
# ─────────────────────────────────────────────────────────────────────────────

def print_previous_trade_summary(ticker: str):
    """Print a summary of the previous trade for context"""
    analysis = analyze_previous_trade(ticker)
    
    if not analysis["has_previous_trade"]:
        print(f"\n📋 No previous trade found for {ticker}")
        return
    
    print(f"\n📋 Previous Trade Summary for {ticker}:")
    print(f"   Verdict: {analysis['verdict']}")
    print(f"   Decision: {analysis['decision_summary'][:200]}...")
    print()


# ================================================================================
# OUTCOME EVALUATION & LEARNING LOOP
# ================================================================================
# Closes the feedback loop: fetch real price movement after a trade, determine
# if the decision was correct, write a reflection into persistent memory so the
# agents get better on every subsequent run.
# ================================================================================

def evaluate_outcome_from_price(
    ticker: str,
    trade_date: str,
    decision: str,
    holding_days: int = 5,
) -> Optional[Dict]:
    """
    Fetch actual closing-price movement and determine if the BUY/SELL was correct.

    Args:
        ticker:       Stock / crypto symbol (yfinance format)
        trade_date:   Date of the original analysis (YYYY-MM-DD)
        decision:     BUY / SELL / HOLD text from the agent
        holding_days: Number of *trading* days to hold before measuring outcome

    Returns:
        Dict with status, prices, return_pct, was_correct — or None on hard error
    """
    import yfinance as yf
    import pandas as pd
    from datetime import datetime as _dt, timedelta as _td

    try:
        trade_dt = _dt.strptime(str(trade_date), "%Y-%m-%d")
        start = (trade_dt - _td(days=5)).strftime("%Y-%m-%d")
        end   = (trade_dt + _td(days=holding_days + 15)).strftime("%Y-%m-%d")

        data = yf.Ticker(ticker.upper()).history(start=start, end=end)

        if data.empty:
            return {"status": "no_data", "reason": f"No price data for {ticker}"}

        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)

        available = data.index
        trade_ts  = pd.Timestamp(trade_date)

        entry_dates = available[available >= trade_ts]
        if len(entry_dates) == 0:
            return {"status": "no_data", "reason": "No trading day on or after analysis date"}

        entry_date  = entry_dates[0]
        entry_price = float(data.loc[entry_date, "Close"])

        exit_dates = available[available > entry_date]
        if len(exit_dates) < holding_days:
            return {
                "status":               "pending",
                "ticker":               ticker,
                "entry_date":           str(entry_date.date()),
                "entry_price":          round(entry_price, 2),
                "holding_days_required": holding_days,
                "trading_days_available": len(exit_dates),
                "reason": (
                    f"Holding period not complete "
                    f"({len(exit_dates)}/{holding_days} trading days elapsed)"
                ),
            }

        exit_date  = exit_dates[min(holding_days - 1, len(exit_dates) - 1)]
        exit_price = float(data.loc[exit_date, "Close"])
        return_pct = ((exit_price - entry_price) / entry_price) * 100

        d_upper = decision.upper().strip()
        if "BUY" in d_upper:
            was_correct = return_pct > 0
        elif "SELL" in d_upper:
            was_correct = return_pct < 0
        else:
            was_correct = None  # HOLD — no correctness concept

        return {
            "status":                "complete",
            "ticker":                ticker,
            "entry_date":            str(entry_date.date()),
            "exit_date":             str(exit_date.date()),
            "entry_price":           round(entry_price, 2),
            "exit_price":            round(exit_price, 2),
            "return_pct":            round(return_pct, 2),
            "dollar_return_per_share": round(exit_price - entry_price, 2),
            "was_correct":           was_correct,
            "decision":              d_upper,
            "holding_days":          holding_days,
        }

    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def load_past_state_for_reflection(ticker: str, date_str: str) -> Optional[Dict]:
    """
    Reload a past LangGraph state from the eval_results JSON log.

    The reflector needs the full state (all analyst reports + debate histories)
    to write meaningful lessons into memory. This function reconstructs that
    minimal structure from the persisted log file.
    """
    log_path = Path(
        f"eval_results/{ticker}/TradingAgentsStrategy_logs"
        f"/full_states_log_{date_str}.json"
    )
    if not log_path.exists():
        return None

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)

        # Log is keyed by trade_date; fall back to first entry when only one run
        state_data = log.get(date_str) or (list(log.values())[0] if log else None)
        if not state_data:
            return None

        from tradingagents.agents.utils.agent_states import (
            InvestDebateState,
            RiskDebateState,
        )

        ids = state_data.get("investment_debate_state", {})
        rds = state_data.get("risk_debate_state", {})

        return {
            "company_of_interest": state_data.get("company_of_interest", ticker),
            "trade_date":          state_data.get("trade_date", date_str),
            "market_report":       state_data.get("market_report", ""),
            "sentiment_report":    state_data.get("sentiment_report", ""),
            "news_report":         state_data.get("news_report", ""),
            "fundamentals_report": state_data.get("fundamentals_report", ""),
            "investment_plan":     state_data.get("investment_plan", ""),
            "trader_investment_plan": state_data.get("trader_investment_decision", ""),
            "final_trade_decision":   state_data.get("final_trade_decision", ""),
            "investment_debate_state": InvestDebateState({
                "history":          ids.get("history", ""),
                "bull_history":     ids.get("bull_history", ""),
                "bear_history":     ids.get("bear_history", ""),
                "current_response": ids.get("current_response", ""),
                "judge_decision":   ids.get("judge_decision", ""),
                "count":            ids.get("count", 0),
            }),
            "risk_debate_state": RiskDebateState({
                "history":                          rds.get("history", ""),
                "aggressive_history":               rds.get("aggressive_history", ""),
                "conservative_history":             rds.get("conservative_history", ""),
                "neutral_history":                  rds.get("neutral_history", ""),
                "current_aggressive_response":      rds.get("current_aggressive_response", ""),
                "current_conservative_response":    rds.get("current_conservative_response", ""),
                "current_neutral_response":         rds.get("current_neutral_response", ""),
                "judge_decision":                   rds.get("judge_decision", ""),
                "latest_speaker":                   rds.get("latest_speaker", ""),
                "count":                            rds.get("count", 0),
            }),
        }
    except Exception as exc:
        print(f"⚠️  Could not load state from {log_path}: {exc}")
        return None


def reflect_on_past_trade(
    ticker: str,
    date_str: str,
    holding_days: int = 5,
) -> Optional[Dict]:
    """
    Full learning-loop for one past trade:
      1. Reload saved state from eval_results log
      2. Fetch real price outcome via yfinance
      3. Call reflect_and_remember so all agent memories are updated
      4. Return outcome + aggregate performance summary
    """
    print(f"\n📂 Loading state for {ticker} / {date_str}…")
    past_state = load_past_state_for_reflection(ticker, date_str)
    if not past_state:
        print(f"❌ No saved state found.")
        print(f"   Expected: eval_results/{ticker}/TradingAgentsStrategy_logs/"
              f"full_states_log_{date_str}.json")
        return None

    final_decision = past_state.get("final_trade_decision", "")
    signal = "HOLD"
    if "BUY"  in final_decision.upper(): signal = "BUY"
    if "SELL" in final_decision.upper(): signal = "SELL"

    print(f"📊 Original decision: {signal}")
    print(f"⏳ Fetching price outcome ({holding_days} trading days)…")

    outcome = evaluate_outcome_from_price(ticker, date_str, signal, holding_days)

    if outcome is None or outcome["status"] == "error":
        reason = (outcome or {}).get("reason", "unknown error")
        print(f"❌ Could not evaluate outcome: {reason}")
        return None

    if outcome["status"] == "pending":
        print(f"⏳ {outcome['reason']}")
        print(f"   Entry: {outcome['entry_date']}  ${outcome['entry_price']:.2f}")
        return outcome

    if outcome["status"] == "no_data":
        print(f"⚠️  {outcome['reason']}")
        return None

    # ── Display outcome ──────────────────────────────────────────────────────
    correct_str = (
        "✅ CORRECT" if outcome["was_correct"] is True  else
        "❌ WRONG"   if outcome["was_correct"] is False else
        "⚪ N/A (HOLD)"
    )
    print(f"\n{'─'*60}")
    print(f"  📈 TRADE OUTCOME: {ticker}")
    print(f"{'─'*60}")
    print(f"  Entry:  {outcome['entry_date']}  ${outcome['entry_price']:.2f}")
    print(f"  Exit:   {outcome['exit_date']}   ${outcome['exit_price']:.2f}")
    print(f"  Return: {outcome['return_pct']:+.2f}%   "
          f"(${outcome['dollar_return_per_share']:+.2f} per share)")
    print(f"  Signal: {signal}  →  {correct_str}")
    print(f"{'─'*60}")

    # ── Reflect and update memory ────────────────────────────────────────────
    print("\n🧠 Running reflection — agents will learn from this outcome…")
    config    = create_ollama_config()
    ta        = TradingAgentsGraph(debug=False, config=config)
    ta.curr_state = past_state
    performance   = ta.reflect_and_remember(outcome["return_pct"])

    print(f"✅ Memory updated for {ticker}\n")
    return {"outcome": outcome, "performance": performance}


def print_memory_performance_report(config: dict = None):
    """
    Pretty-print aggregate success rates for every agent memory component.
    Reads the persisted JSON files directly — no LLM calls needed.
    """
    from tradingagents.agents.utils.memory import FinancialSituationMemory

    if config is None:
        config = create_ollama_config()

    memory_names = [
        "bull_memory",
        "bear_memory",
        "trader_memory",
        "invest_judge_memory",
        "risk_manager_memory",
    ]

    print(f"\n{'='*80}")
    print("🧠  AGENT MEMORY PERFORMANCE".center(80))
    print(f"{'='*80}")
    print(
        f"  {'Agent':<22} {'Records':>8} {'Evaluated':>10} "
        f"{'Correct':>8} {'Success':>9} {'Avg Return':>12}"
    )
    print(f"  {'─'*22} {'─'*8} {'─'*10} {'─'*8} {'─'*9} {'─'*12}")

    totals = {"records": 0, "evaluated": 0, "correct": 0}

    for name in memory_names:
        mem     = FinancialSituationMemory(name, config)
        s       = mem.get_performance_summary()
        label   = name.replace("_memory", "").replace("_", " ").title()
        rate    = f"{s['success_rate']:.1f}%" if s["success_rate"]   is not None else "—"
        avg_ret = f"{s['average_returns']:+.2f}%" if s["average_returns"] is not None else "—"

        print(
            f"  {label:<22} {s['total_records']:>8} {s['evaluated_records']:>10} "
            f"{s['correct_records']:>8} {rate:>9} {avg_ret:>12}"
        )
        totals["records"]   += s["total_records"]
        totals["evaluated"] += s["evaluated_records"]
        totals["correct"]   += s["correct_records"]

    print(f"  {'─'*22} {'─'*8} {'─'*10} {'─'*8} {'─'*9} {'─'*12}")
    total_rate = (
        f"{round(totals['correct'] / totals['evaluated'] * 100, 1)}%"
        if totals["evaluated"] else "—"
    )
    print(
        f"  {'TOTAL':<22} {totals['records']:>8} {totals['evaluated']:>10} "
        f"{totals['correct']:>8} {total_rate:>9}"
    )
    print(f"{'='*80}")

    # Show storage path from any memory instance
    sample = FinancialSituationMemory("bull_memory", config)
    print(f"  📁 Stored at: {sample.storage_dir}")
    print()


# ================================================================================
# TRADING FUNCTIONS
# ================================================================================
# Core trading analysis functions for intraday and swing trading strategies.
# Each function handles configuration, execution, and result reporting.
# ================================================================================

# ─────────────────────────────────────────────────────────────────────────────
# Intraday Trading (Short-term, 1-day focus)
# ─────────────────────────────────────────────────────────────────────────────

def run_intraday_analysis(ticker: str, config: dict = None) -> Tuple[any, str]:
    """
    Run intraday trading analysis (short-term, 1-day focus).
    
    Focus:
    - Short-term momentum
    - Technical indicators
    - Quick decision making
    - Lower debate rounds
    
    Args:
        ticker: Stock/crypto ticker symbol
        config: Optional custom configuration
    
    Returns:
        Tuple of (graph_state, decision)
    """
    print(f"\n{'='*80}")
    print(f"🔥 INTRADAY ANALYSIS: {ticker}")
    print(f"{'='*80}")
    
    # Check previous trade
    print_previous_trade_summary(ticker)
    
    # Setup configuration for intraday
    if config:
        trading_config = config.copy()
    else:
        # Use Ollama by default
        trading_config = create_ollama_config()
    
    # Override debate rounds for intraday
    trading_config["max_debate_rounds"] = TradingConfig.INTRADAY_CONFIG["max_debate_rounds"]
    
    # Use today's date for intraday
    analysis_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"📅 Analysis Date: {analysis_date}")
    print(f"⚡ Strategy: Intraday (Short-term)")
    print(f"🎯 Focus: {TradingConfig.INTRADAY_CONFIG['focus']}")
    print(f"⏱️  Timeframe: {TradingConfig.INTRADAY_CONFIG['timeframe']}")
    print()
    
    # Initialize and run with strategy parameters
    ta = TradingAgentsGraph(debug=True, config=trading_config)
    state, decision = ta.propagate(
        ticker, 
        analysis_date, 
        trading_strategy="intraday",
        strategy_timeframe=TradingConfig.INTRADAY_CONFIG['timeframe']
    )
    
    print(f"\n✅ Intraday analysis complete for {ticker}")
    print(f"📊 Decision: {decision[:200] if decision else 'No decision'}...")
    
    return state, decision


# ─────────────────────────────────────────────────────────────────────────────
# Swing Trading (Medium-term, 3-10 day focus)
# ─────────────────────────────────────────────────────────────────────────────

def run_swing_analysis(ticker: str, config: dict = None) -> Tuple[any, str]:
    """
    Run swing trading analysis (medium-term, 3-10 day focus).
    
    Focus:
    - Medium-term trends
    - Fundamental analysis
    - More thorough debate
    - Higher research depth
    
    Args:
        ticker: Stock/crypto ticker symbol
        config: Optional custom configuration
    
    Returns:
        Tuple of (graph_state, decision)
    """
    print(f"\n{'='*80}")
    print(f"📈 SWING TRADING ANALYSIS: {ticker}")
    print(f"{'='*80}")
    
    # Check previous trade
    print_previous_trade_summary(ticker)
    
    # Setup configuration for swing trading
    if config:
        trading_config = config.copy()
    else:
        # Use Ollama by default
        trading_config = create_ollama_config()
    
    # Override debate rounds for swing trading
    trading_config["max_debate_rounds"] = TradingConfig.SWING_CONFIG["max_debate_rounds"]
    
    # Use today's date
    analysis_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"📅 Analysis Date: {analysis_date}")
    print(f"📊 Strategy: Swing Trading (Medium-term)")
    print(f"🎯 Focus: {TradingConfig.SWING_CONFIG['focus']}")
    print(f"⏱️  Timeframe: {TradingConfig.SWING_CONFIG['timeframe']}")
    print()
    
    # Initialize and run with strategy parameters
    ta = TradingAgentsGraph(debug=True, config=trading_config)
    state, decision = ta.propagate(
        ticker, 
        analysis_date,
        trading_strategy="swing",
        strategy_timeframe=TradingConfig.SWING_CONFIG['timeframe']
    )
    
    print(f"\n✅ Swing analysis complete for {ticker}")
    print(f"📊 Decision: {decision[:200] if decision else 'No decision'}...")
    
    return state, decision


# ─────────────────────────────────────────────────────────────────────────────
# Batch Analysis
# ─────────────────────────────────────────────────────────────────────────────

def batch_analyze(tickers: List[str], strategy: str = "swing", delay: int = 5) -> Dict[str, any]:
    """
    Analyze multiple tickers in batch.
    
    Args:
        tickers: List of ticker symbols
        strategy: "intraday" or "swing"
        delay: Delay between analyses (seconds)
    
    Returns:
        Dictionary of results keyed by ticker
    """
    results = {}
    
    analyze_func = run_intraday_analysis if strategy == "intraday" else run_swing_analysis
    
    print(f"\n🚀 Starting batch {strategy} analysis for {len(tickers)} tickers")
    print(f"📋 Tickers: {', '.join(tickers)}")
    print()
    
    for i, ticker in enumerate(tickers, 1):
        try:
            print(f"\n[{i}/{len(tickers)}] Analyzing {ticker}...")
            state, decision = analyze_func(ticker)
            results[ticker] = {
                "success": True,
                "state": state,
                "decision": decision
            }
            
            # Delay between analyses to avoid rate limits
            if i < len(tickers):
                print(f"\n⏳ Waiting {delay} seconds before next analysis...")
                time.sleep(delay)
                
        except Exception as e:
            print(f"\n❌ Error analyzing {ticker}: {e}")
            results[ticker] = {
                "success": False,
                "error": str(e)
            }
    
    print(f"\n{'='*80}")
    print(f"✅ Batch analysis complete!")
    print(f"   Successful: {sum(1 for r in results.values() if r.get('success'))}")
    print(f"   Failed: {sum(1 for r in results.values() if not r.get('success'))}")
    print(f"{'='*80}")
    
    return results


# ================================================================================
# UTILITY FUNCTIONS
# ================================================================================
# Helper functions for formatting, file operations, and user interface.
# ================================================================================

# ─────────────────────────────────────────────────────────────────────────────
# Display Utilities
# ─────────────────────────────────────────────────────────────────────────────

def print_header(title: str):
    """Print a formatted header"""
    print(f"\n{'='*80}")
    print(f"{title:^80}")
    print(f"{'='*80}\n")


def display_analysis_resume(ticker: str, decision: str, strategy: str = "swing"):
    """
    Display detailed analysis resume for a ticker.
    Shows the full trading decision and analysis details.
    
    Args:
        ticker: Stock/crypto ticker symbol
        decision: Trading decision text
        strategy: Analysis strategy ("swing" or "intraday")
    """
    print(f"\n{'='*80}")
    print(f"📊 DETAILED ANALYSIS RESUME: {ticker}".center(80))
    print(f"{'='*80}\n")
    
    print(f"Strategy: {strategy.upper()}")
    print(f"Ticker: {ticker}")
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n{'-'*80}\n")
    
    # Display full decision
    print("📋 TRADING DECISION:\n")
    if decision:
        print(decision)
    else:
        print("No decision available")
    
    print(f"\n{'-'*80}\n")
    
    # Display report location
    ticker_dir = TradingConfig.RESULTS_DIR / ticker
    if ticker_dir.exists():
        date_folders = sorted([d for d in ticker_dir.iterdir() if d.is_dir()], reverse=True)
        if date_folders:
            latest_report = date_folders[0]
            print(f"📁 Full reports saved to: {latest_report.absolute()}")
            
            reports_dir = latest_report / "reports"
            if reports_dir.exists():
                report_files = list(reports_dir.glob("*.md"))
                print(f"📄 Report files ({len(report_files)}):")
                for report_file in report_files:
                    print(f"   • {report_file.name}")
    
    print(f"\n{'='*80}\n")


# ─────────────────────────────────────────────────────────────────────────────
# File Operations
# ─────────────────────────────────────────────────────────────────────────────

def save_batch_results(results: Dict[str, any], filename: str = None):
    """
    Save batch analysis results to JSON file.
    
    Args:
        results: Dictionary of results from batch_analyze()
        filename: Optional filename, defaults to timestamp-based name
    """
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"batch_results_{timestamp}.json"
    
    output_path = Path(filename)
    
    # Prepare results for JSON serialization (remove non-serializable objects)
    serializable_results = {}
    for ticker, result in results.items():
        serializable_results[ticker] = {
            "success": result.get("success", False),
            "decision": result.get("decision", ""),
            "error": result.get("error", "")
        }
    
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_tickers": len(results),
        "successful": sum(1 for r in results.values() if r.get("success")),
        "failed": sum(1 for r in results.values() if not r.get("success")),
        "results": serializable_results
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n💾 Results saved to: {output_path.absolute()}")


# ─────────────────────────────────────────────────────────────────────────────
# Menu System
# ─────────────────────────────────────────────────────────────────────────────

def main_memory_and_learning():
    """Interactive sub-menu for the persistent memory & learning loop."""
    while True:
        print_header("MEMORY & LEARNING LOOP")
        print("1. 📊 Show memory performance report")
        print("2. 🔁 Evaluate outcome for a past trade")
        print("3. 🗑️  Clear all agent memories")
        print("0. ↩  Back")
        print(f"\n{'─'*80}")

        choice = input("Choose option: ").strip()

        if choice == "0":
            break

        elif choice == "1":
            print_memory_performance_report()

        elif choice == "2":
            ticker = input("Ticker (e.g. AAPL, BTC-USD): ").strip().upper()
            if not ticker:
                print("❌ No ticker provided"); continue

            date_str = input("Analysis date (YYYY-MM-DD): ").strip()
            try:
                from datetime import datetime as _dt2
                _dt2.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                print("❌ Date must be YYYY-MM-DD format"); continue

            days_input = input("Holding period in trading days [5]: ").strip()
            holding_days = int(days_input) if days_input.isdigit() else 5

            reflect_on_past_trade(ticker, date_str, holding_days)

        elif choice == "3":
            confirm = input(
                "⚠️  This will permanently erase all agent memories. "
                "Type 'YES' to confirm: "
            ).strip()
            if confirm == "YES":
                from tradingagents.agents.utils.memory import FinancialSituationMemory
                cfg = create_ollama_config()
                for name in [
                    "bull_memory", "bear_memory", "trader_memory",
                    "invest_judge_memory", "risk_manager_memory",
                ]:
                    FinancialSituationMemory(name, cfg).clear()
                print("✅ All agent memories cleared.")
            else:
                print("Cancelled.")

        else:
            print("Invalid option. Please try again.")

        input("\nPress Enter to continue…")


def print_menu():
    """Display the main menu"""
    print_header("TRADING AGENT - MAIN MENU")
    print(f"Current Models: {TradingConfig.current_deep_think_model} / {TradingConfig.current_quick_think_model}")
    print(f"Active Analysts: {', '.join(TradingConfig.current_analysts)}")
    print(f"Research Depth: {TradingConfig.current_research_depth.upper()}")
    print(f"\n{'─'*80}\n")
    print("1. 📊 Single Ticker Analysis (Swing)")
    print("2. ⚡ Single Ticker Analysis (Intraday)")
    print("3. 📈 Batch Analysis (Swing)")
    print("4. 🔥 Batch Analysis (Intraday)")
    print("5. 📋 Review Previous Trades")
    print("6. 🎯 Analyze Watchlist")
    print("7. 🔍 Check Single Ticker History")
    print("8. 🤖 Model Configuration")
    print("9. 🎛️  Analyst & Research Settings")
    print("A. 💼 Portfolio Tracking (Future Integration)")
    print("B. 🧠 Memory & Learning")
    print("0. ❌ Exit")
    print(f"\n{'─'*80}")


# ================================================================================
# MAIN EXECUTION FUNCTIONS
# ================================================================================
# Individual menu option handlers for different trading operations.
# Each function provides interactive prompts and executes the selected operation.
# ================================================================================

# ─────────────────────────────────────────────────────────────────────────────
# Single Ticker Analysis
# ─────────────────────────────────────────────────────────────────────────────

def main_single_swing():
    """Execute single ticker swing analysis"""
    print_header("SINGLE TICKER - SWING ANALYSIS")
    
    ticker = input("Enter ticker symbol (e.g., AAPL, TSLA, BTC-USD): ").strip().upper()
    
    if not ticker:
        print("❌ No ticker provided")
        return
    
    try:
        state, decision = run_swing_analysis(ticker)
        
        # Reports are auto-saved by TradingAgentsGraph
        print("\n✅ Reports automatically saved")
        
        # Ask if user wants to see detailed resume
        show_resume = input("\n📊 Display detailed analysis resume? (y/n): ").strip().lower()
        if show_resume == 'y':
            display_analysis_resume(ticker, decision, "swing")
    except Exception as e:
        print(f"❌ Error: {e}")


def main_single_intraday():
    """Execute single ticker intraday analysis"""
    print_header("SINGLE TICKER - INTRADAY ANALYSIS")
    
    ticker = input("Enter ticker symbol (e.g., AAPL, TSLA, BTC-USD): ").strip().upper()
    
    if not ticker:
        print("❌ No ticker provided")
        return
    
    try:
        state, decision = run_intraday_analysis(ticker)
        
        # Reports are auto-saved by TradingAgentsGraph
        print("\n✅ Reports automatically saved")
        
        # Ask if user wants to see detailed resume
        show_resume = input("\n📊 Display detailed analysis resume? (y/n): ").strip().lower()
        if show_resume == 'y':
            display_analysis_resume(ticker, decision, "intraday")
    except Exception as e:
        print(f"❌ Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Batch Analysis Operations
# ─────────────────────────────────────────────────────────────────────────────

def main_batch_analysis(strategy: str = "swing"):
    """Execute batch analysis"""
    strategy_name = "SWING" if strategy == "swing" else "INTRADAY"
    print_header(f"BATCH ANALYSIS - {strategy_name}")
    
    print("Enter tickers separated by commas (e.g., AAPL, MSFT, GOOGL)")
    print("Or press Enter to use default watchlist")
    user_input = input("> ").strip()
    
    if user_input:
        tickers = [t.strip().upper() for t in user_input.split(",")]
    else:
        tickers = get_default_watchlist()
        print(f"📋 Using default watchlist: {', '.join(tickers)}")
    
    delay = input("\nDelay between analyses in seconds (default: 5): ").strip()
    delay = int(delay) if delay.isdigit() else 5
    
    print(f"\n🚀 Starting {strategy} analysis for {len(tickers)} tickers...")
    print(f"⏱️  Delay: {delay} seconds between analyses")
    
    try:
        results = batch_analyze(tickers, strategy=strategy, delay=delay)
        
        # Auto-save batch results
        save_batch_results(results)
        print("✅ Batch summary automatically saved")
        
        # Ask if user wants to see detailed resume for each ticker
        show_details = input("\n📊 Display detailed resumes for analyzed tickers? (y/n): ").strip().lower()
        if show_details == 'y':
            for ticker, result in results.items():
                if result.get("success"):
                    decision = result.get("decision", "No decision available")
                    display_analysis_resume(ticker, decision, strategy)
                    input("\nPress Enter to continue to next ticker...")
    
    except Exception as e:
        print(f"❌ Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Review and History Operations
# ─────────────────────────────────────────────────────────────────────────────

def main_review_previous_trades():
    """Review previous trades for multiple tickers"""
    print_header("REVIEW PREVIOUS TRADES")
    
    print("Enter tickers separated by commas (e.g., AAPL, MSFT, GOOGL)")
    print("Or press Enter to check default watchlist")
    user_input = input("> ").strip()
    
    if user_input:
        tickers = [t.strip().upper() for t in user_input.split(",")]
    else:
        tickers = get_default_watchlist()
    
    print(f"\n📊 Reviewing previous trades for {len(tickers)} tickers...\n")
    
    found_count = 0
    for ticker in tickers:
        analysis = analyze_previous_trade(ticker)
        
        print(f"{'─'*80}")
        print(f"📈 {ticker}")
        print(f"{'─'*80}")
        
        if analysis["has_previous_trade"]:
            found_count += 1
            print(f"✅ Previous Trade Found")
            print(f"   Verdict: {analysis['verdict']}")
            print(f"   Decision: {analysis['decision_summary'][:150]}...")
            print(f"   Market: {analysis['market_conditions'][:100]}...")
        else:
            print(f"ℹ️  No previous trade found")
        print()
    
    print(f"{'='*80}")
    print(f"Summary: Found {found_count}/{len(tickers)} previous trades")
    print(f"{'='*80}")


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist Operations
# ─────────────────────────────────────────────────────────────────────────────

def main_analyze_watchlist():
    """Analyze entire watchlist"""
    print_header("ANALYZE WATCHLIST")
    
    # Get watchlist from TradingView
    tradingview_tickers = get_tradingview_watchlist()
    auto_discovered = auto_discover_tickers()
    all_tickers = merge_watchlists(tradingview_tickers, auto_discovered)
    
    print(f"📋 Total tickers in watchlist: {len(all_tickers)}")
    print(f"📊 Tickers: {', '.join(all_tickers[:20])}")
    if len(all_tickers) > 20:
        print(f"    ... and {len(all_tickers) - 20} more")
    
    print("\nChoose analysis type:")
    print("1. Swing Trading (thorough)")
    print("2. Intraday Trading (fast)")
    
    choice = input("> ").strip()
    strategy = "swing" if choice == "1" else "intraday"
    
    # Ask how many to analyze
    print(f"\nHow many tickers to analyze? (max: {len(all_tickers)})")
    count = input(f"Press Enter for all ({len(all_tickers)}): ").strip()
    
    if count.isdigit():
        count = min(int(count), len(all_tickers))
    else:
        count = len(all_tickers)
    
    tickers_to_analyze = all_tickers[:count]
    
    delay = input("\nDelay between analyses in seconds (default: 5): ").strip()
    delay = int(delay) if delay.isdigit() else 5
    
    print(f"\n🚀 Starting {strategy} analysis for {len(tickers_to_analyze)} tickers...")
    
    try:
        results = batch_analyze(tickers_to_analyze, strategy=strategy, delay=delay)
        
        # Auto-save batch results
        save_batch_results(results)
        print("✅ Batch summary automatically saved")
        
        # Ask if user wants to see detailed resume for each ticker
        show_details = input("\n📊 Display detailed resumes for analyzed tickers? (y/n): ").strip().lower()
        if show_details == 'y':
            for ticker, result in results.items():
                if result.get("success"):
                    decision = result.get("decision", "No decision available")
                    display_analysis_resume(ticker, decision, strategy)
                    input("\nPress Enter to continue to next ticker...")
    
    except Exception as e:
        print(f"❌ Error: {e}")


def main_check_ticker_history():
    """Check history and details for a single ticker"""
    print_header("CHECK TICKER HISTORY")
    
    ticker = input("Enter ticker symbol: ").strip().upper()
    
    if not ticker:
        print("❌ No ticker provided")
        return
    
    print(f"\n{'─'*80}")
    print(f"📊 Checking history for {ticker}")
    print(f"{'─'*80}\n")
    
    # Check if ticker folder exists
    ticker_dir = TradingConfig.RESULTS_DIR / ticker
    
    if not ticker_dir.exists():
        print(f"ℹ️  No analysis history found for {ticker}")
        print(f"    Run an analysis first to create history.")
        return
    
    # List all date folders
    date_folders = sorted([d for d in ticker_dir.iterdir() if d.is_dir()], reverse=True)
    
    if not date_folders:
        print(f"ℹ️  No analysis reports found for {ticker}")
        return
    
    print(f"✅ Found {len(date_folders)} analysis report(s):\n")
    
    for i, date_folder in enumerate(date_folders, 1):
        date_name = date_folder.name
        reports_dir = date_folder / "reports"
        
        if reports_dir.exists():
            report_files = list(reports_dir.glob("*.md"))
            print(f"{i}. {date_name} ({len(report_files)} reports)")
        else:
            print(f"{i}. {date_name} (no reports)")
    
    # Show latest trade details
    print(f"\n{'─'*80}")
    print(f"Latest Trade Details:")
    print(f"{'─'*80}\n")
    
    analysis = analyze_previous_trade(ticker)
    
    if analysis["has_previous_trade"]:
        print(f"📅 Date: {date_folders[0].name}")
        print(f"🎯 Verdict: {analysis['verdict']}")
        print(f"\n📝 Decision Summary:")
        print(f"{analysis['decision_summary']}")
        print(f"\n📊 Market Conditions:")
        print(f"{analysis['market_conditions']}")
    else:
        print("ℹ️  No readable trade data found")


# ─────────────────────────────────────────────────────────────────────────────
# Model Configuration
# ─────────────────────────────────────────────────────────────────────────────

def main_model_configuration():
    """Configure LLM models"""
    print_header("MODEL CONFIGURATION")
    
    # Check Ollama status
    if not check_ollama_running():
        print("❌ Ollama is not running!")
        print("\nPlease start Ollama:")
        print("  • Open a new terminal")
        print("  • Run: ollama serve")
        print("\nOr download Ollama: https://ollama.ai")
        return
    
    print("✅ Ollama is running\n")
    
    # Show current config
    print(f"Current Configuration:")
    print(f"  Deep Think Model: {TradingConfig.current_deep_think_model}")
    print(f"  Quick Think Model: {TradingConfig.current_quick_think_model}")
    print()
    
    # Display available models
    display_available_models()
    
    print("\nWhat would you like to do?")
    print("1. Change Deep Think Model (used for complex analysis)")
    print("2. Change Quick Think Model (used for fast decisions)")
    print("3. Download New Model")
    print("4. Browse HuggingFace Models")
    print("5. Test Current Models")
    print("0. Back to Main Menu")
    
    choice = input("\nSelect option: ").strip()
    
    if choice == "1":
        print("\n🧠 Select Deep Think Model:")
        model = select_model_interactive()
        if model:
            # Ensure model is available
            if check_model_exists(model) or ensure_model_available(model):
                TradingConfig.current_deep_think_model = model
                print(f"\n✅ Deep Think Model set to: {model}")
            else:
                print("\n❌ Model not available")
    
    elif choice == "2":
        print("\n⚡ Select Quick Think Model:")
        model = select_model_interactive()
        if model:
            # Ensure model is available
            if check_model_exists(model) or ensure_model_available(model):
                TradingConfig.current_quick_think_model = model
                print(f"\n✅ Quick Think Model set to: {model}")
            else:
                print("\n❌ Model not available")
    
    elif choice == "3":
        print("\n🔽 Download New Model")
        print("\nPopular models:")
        print("  • llama3:8b - Meta's Llama 3 (8B params)")
        print("  • mistral:7b - Mistral AI (7B params)")
        print("  • qwen2:7b - Alibaba Qwen 2 (7B params)")
        print("  • phi3:medium - Microsoft Phi-3")
        print("  • gemma2:9b - Google Gemma 2")
        print()
        
        model_name = input("Enter model name: ").strip()
        if model_name:
            pull_ollama_model(model_name)
    
    elif choice == "4":
        print("\n🤗 HuggingFace Model Browser")
        hf_models = search_huggingface_models()
        print("\nPopular Models Available via Ollama:\n")
        
        for i, model in enumerate(hf_models, 1):
            print(f"{i}. {model['name']}")
            print(f"   📝 {model['description']}")
            print(f"   🔗 {model['repo']}")
            print()
        
        choice = input(f"Download model (1-{len(hf_models)}) or 0 to cancel: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(hf_models):
            selected = hf_models[int(choice) - 1]
            download_huggingface_model_to_ollama(selected["name"], selected["repo"])
    
    elif choice == "5":
        print("\n🧪 Testing Models...\n")
        print(f"Deep Think: {TradingConfig.current_deep_think_model}")
        if check_model_exists(TradingConfig.current_deep_think_model):
            print("  ✅ Available")
        else:
            print("  ❌ Not found")
        
        print(f"\nQuick Think: {TradingConfig.current_quick_think_model}")
        if check_model_exists(TradingConfig.current_quick_think_model):
            print("  ✅ Available")
        else:
            print("  ❌ Not found")
    
    elif choice != "0":
        print("❌ Invalid option")


# ─────────────────────────────────────────────────────────────────────────────
# Analyst & Research Configuration
# ─────────────────────────────────────────────────────────────────────────────

def main_analyst_research_settings():
    """Configure analyst agents and research depth"""
    print_header("ANALYST & RESEARCH SETTINGS")
    
    print("Configure which analysts to activate and research depth.\n")
    
    # Show current configuration
    print(f"Current Configuration:")
    print(f"  Active Analysts: {', '.join(TradingConfig.current_analysts)}")
    print(f"  Research Depth: {TradingConfig.current_research_depth.upper()}")
    print()
    
    print("What would you like to configure?")
    print("1. Change Active Analysts")
    print("2. Change Research Depth")
    print("3. Reset to Defaults")
    print("0. Back to Main Menu")
    
    choice = input("\nSelect option: ").strip()
    
    if choice == "1":
        print(f"\n{'─'*80}")
        print("CONFIGURE ACTIVE ANALYSTS")
        print(f"{'─'*80}\n")
        
        print("Available analysts:")
        for i, analyst in enumerate(TradingConfig.AVAILABLE_ANALYSTS, 1):
            active = "✅" if analyst in TradingConfig.current_analysts else "⬜"
            print(f"  {i}. {active} {analyst}")
        
        print("\nEnter analyst numbers to toggle (comma-separated, e.g., 1,3,4)")
        print("Or press Enter to keep current selection")
        
        selection = input("> ").strip()
        
        if selection:
            try:
                indices = [int(x.strip()) for x in selection.split(",")]
                new_analysts = []
                
                for idx in indices:
                    if 1 <= idx <= len(TradingConfig.AVAILABLE_ANALYSTS):
                        analyst = TradingConfig.AVAILABLE_ANALYSTS[idx - 1]
                        if analyst not in new_analysts:
                            new_analysts.append(analyst)
                
                if new_analysts:
                    TradingConfig.current_analysts = new_analysts
                    print(f"\n✅ Active analysts updated: {', '.join(new_analysts)}")
                else:
                    print("\n⚠️  No valid analysts selected. Keeping current configuration.")
            
            except ValueError:
                print("\n❌ Invalid input. Please enter numbers separated by commas.")
    
    elif choice == "2":
        print(f"\n{'─'*80}")
        print("CONFIGURE RESEARCH DEPTH")
        print(f"{'─'*80}\n")
        
        print("Select research depth:")
        print("  1. Shallow - Quick research, few debate and strategy discussion rounds")
        print("  2. Medium - Middle ground, moderate debate rounds and strategy discussion")
        print("  3. Deep - Comprehensive research, in-depth debate and strategy discussion")
        
        depth_choice = input("\nSelect (1-3): ").strip()
        
        depth_map = {
            "1": "shallow",
            "2": "medium",
            "3": "deep"
        }
        
        if depth_choice in depth_map:
            TradingConfig.current_research_depth = depth_map[depth_choice]
            print(f"\n✅ Research depth set to: {TradingConfig.current_research_depth.upper()}")
        else:
            print("\n❌ Invalid selection. Keeping current configuration.")
    
    elif choice == "3":
        print(f"\n{'─'*80}")
        print("RESET TO DEFAULTS")
        print(f"{'─'*80}\n")
        
        confirm = input("Reset analysts and research depth to defaults? (y/n): ").strip().lower()
        
        if confirm == 'y':
            TradingConfig.current_analysts = TradingConfig.DEFAULT_ANALYSTS.copy()
            TradingConfig.current_research_depth = TradingConfig.DEFAULT_RESEARCH_DEPTH
            print("\n✅ Configuration reset to defaults:")
            print(f"   Analysts: {', '.join(TradingConfig.current_analysts)}")
            print(f"   Research Depth: {TradingConfig.current_research_depth.upper()}")
        else:
            print("\n⏭️  Reset cancelled")
    
    elif choice != "0":
        print("❌ Invalid option")


# ================================================================================
# MAIN FUNCTION
# ================================================================================
# Entry point for the interactive trading agent application.
# Provides a menu-driven interface for all trading operations.
# ================================================================================

def main():
    """
    Main function to run the trading agent with interactive menu.
    
    Provides options for:
    - Single ticker analysis (swing/intraday)
    - Batch analysis
    - Review previous trades
    - Analyze watchlist
    - Check ticker history
    """
    print_header("🚀 TRADING AGENT - MULTI-ASSET ANALYSIS")
    print("Welcome to the Enhanced Trading Agent :)")
    print("Any contribution is welcome !")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Version: 2.0\n")
    print("Author : Paul B. & Mathieu L.")
    
    # Model selection on startup
    if not prompt_model_selection_on_startup():
        # User chose to exit or Ollama not running
        return
    
    # Ready to start
    print(f"{'='*80}")
    print("✅ READY TO START".center(80))
    print(f"{'='*80}\n")
    print(f"Current Configuration:")
    print(f"  🧠 Deep Think: {TradingConfig.current_deep_think_model}")
    print(f"  ⚡ Quick Think: {TradingConfig.current_quick_think_model}")
    print(f"  👥 Active Analysts: {', '.join(TradingConfig.current_analysts)}")
    print(f"  🔬 Research Depth: {TradingConfig.current_research_depth.upper()}\n")
    
    input("Press Enter to continue to main menu...")
    
    while True:
        print_menu()
        choice = input("Select an option (0-9, A, B): ").strip().upper()
        
        try:
            if choice == "1":
                main_single_swing()
            elif choice == "2":
                main_single_intraday()
            elif choice == "3":
                main_batch_analysis(strategy="swing")
            elif choice == "4":
                main_batch_analysis(strategy="intraday")
            elif choice == "5":
                main_review_previous_trades()
            elif choice == "6":
                main_analyze_watchlist()
            elif choice == "7":
                main_check_ticker_history()
            elif choice == "8":
                main_model_configuration()
            elif choice == "9":
                main_analyst_research_settings()
            elif choice == "A":
                manage_portfolio_tracking()
            elif choice == "B":
                main_memory_and_learning()
            elif choice == "0":
                print_header("👋 GOODBYE")
                print("Thank you for using Trading Agent!")
                break
            else:
                print("❌ Invalid option. Please select 0-9 or A.")
        
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
        
        # Pause before showing menu again
        if choice in ["1", "2", "3", "4", "5", "6", "7", "8", "9", "A", "B"]:
            input("\n Press Enter to continue...")

# ================================================================================
# SCRIPT ENTRY POINT
# ================================================================================

if __name__ == "__main__":
    # Run the main function with interactive menu
    main()
    
    # ============================================================================
    # ALTERNATIVE: Quick execution without menu (uncomment to use)
    # ============================================================================
    
    # # Example 1: Single ticker swing analysis
    # # run_swing_analysis("AAPL")
    
    # # Example 2: Single ticker intraday analysis
    # # run_intraday_analysis("TSLA")
    
    # # Example 3: Batch analyze specific tickers
    # # tickers = ["AAPL", "MSFT", "GOOGL"]
    # # results = batch_analyze(tickers, strategy="swing", delay=5)
    
    # # Example 4: Analyze entire watchlist
    # # watchlist = get_tradingview_watchlist()
    # # results = batch_analyze(watchlist[:5], strategy="swing", delay=5)
    
    # # Example 5: Check previous trade
    # # analysis = analyze_previous_trade("SPY")
    # # print(json.dumps(analysis, indent=2))