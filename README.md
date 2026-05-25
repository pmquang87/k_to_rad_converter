# LS-DYNA to OpenRadioss Converter (k2rad)

This tool converts LS-DYNA keyword files (`.k`) to OpenRadioss format (`.rad`).

## Features

- Converts basic LS-DYNA structural components to OpenRadioss.
- CLI interface for easy batch processing.
- Extensible handler-based architecture for keyword mapping.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/k_to_rad_converter.git
   cd k_to_rad_converter
   ```

2. (Optional) Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

## Usage

Run the converter using `k2rad.py`:

```bash
python k2rad.py input_model.k [output_prefix]
```

Example with units:
```bash
python k2rad.py model.k --units Mg mm s
```

## Project Structure

- `k2rad.py`: Main entry point.
- `k2rad/`: Core library containing the parser, writer, and keyword handlers.
- `run_converter.py`: Alternative execution script.

## License

[Add License Type Here, e.g., MIT]
