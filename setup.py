"""
Jutsu Labs Engine - Modular Backtesting Engine for Trading Strategies
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="jutsu-engine",
    version="0.1.0",
    description="Modular backtesting engine for trading strategies",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Anil Goparaju, Padma Priya Garnepudi",
    author_email="",
    url="https://github.com/yourusername/jutsu-engine",
    packages=find_packages(exclude=["tests*", "docs*"]),
    python_requires=">=3.10",
    install_requires=[
        "sqlalchemy>=2.0.0",
        "alembic>=1.12.0",
        "python-dotenv>=1.0.0",
        "pyyaml>=6.0.1",
        "schwab-py>=0.3.0",
        "pandas>=2.1.0",
        "numpy>=1.25.0",
        "click>=8.1.7",
        "python-dateutil>=2.8.2",
        "pydantic>=2.5.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.3",
            "pytest-cov>=4.1.0",
            "pytest-mock>=3.12.0",
            "black>=23.12.0",
            "isort>=5.13.0",
            "flake8>=7.0.0",
            "mypy>=1.7.1",
        ],
        "docs": [
            "sphinx>=7.2.6",
            "sphinx-rtd-theme>=2.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "jutsu=jutsu_engine.cli.main:cli",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Financial and Insurance Industry",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="backtesting trading finance algorithmic-trading",
)
