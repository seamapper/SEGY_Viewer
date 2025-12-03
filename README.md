# SEGY Viewer

A Python application for viewing and processing SEGY seismic data files, developed at UNH/CCOM-JHC (University of New Hampshire, Center for Coastal and Ocean Mapping - Joint Hydrographic Center).

## Features

- **Interactive SEGY File Viewing**
  - Load and display SEGY seismic data with customizable colormaps
  - Adjustable amplitude clipping (clip percentile)
  - Full resolution plot export
  - Interactive trace selection and header information display

- **Header Information Display**
  - View binary headers with expandable descriptions
  - Display text headers
  - Trace header information with clickable field names
  - Field descriptions for trace header values

- **Export Capabilities**
  - Save plots as PNG images (standard or full resolution)
  - Export navigation data as shapefiles (point and line geometries)
  - Save header information to text files
  - Automatic coordinate conversion (seconds of arc to decimal degrees)

- **Batch Processing**
  - Process multiple SEGY files in one operation
  - Generate plots, shapefiles, and header info files for each file
  - Create combined navigation shapefiles from multiple files
  - Progress tracking and error handling

- **Shapefile Features**
  - Point shapefiles with CDP coordinates and trace information
  - Line shapefiles connecting navigation points
  - Date/time fields (START_DT, END_DT for lines, DATETIME for points)
  - Automatic coordinate system detection (WGS84 for geographic coordinates)

## Requirements

- Python 3.8 or higher
- PyQt6
- matplotlib
- numpy
- pandas
- segyio
- geopandas (optional, for shapefile export)
- fiona (optional, fallback for shapefile export)
- shapely (optional, for shapefile export)

## Installation

### From Source

1. Clone the repository:
```bash
git clone https://github.com/seamapper/SEGY_Viewer.git
cd SEGY_Viewer
```

2. Install dependencies:
```bash
pip install PyQt6 matplotlib numpy pandas segyio geopandas
```

### Windows Executable

Pre-built Windows executables are available in the `dist/` directory. The executable is a single-file application that includes all dependencies.

## Usage

### Running the Application

**From source:**
```bash
python segy_viewer.py
```

**Windows executable:**
Double-click `CCOM_SEGY_Viewer_v2025.05.exe` (or the latest version in the `dist/` directory)

### Basic Workflow

1. **Open a SEGY File**
   - Click "Open SEGY File" button
   - Select your `.sgy` or `.segy` file
   - The file will load and display automatically

2. **Adjust Display Settings**
   - **Clip %**: Adjust amplitude clipping (default: 99%)
   - **Colormap**: Select from available colormaps (BuPu, RdBu, seismic, gray, viridis, plasma)
   - Click "Update Plot" to apply changes

3. **View Header Information**
   - Binary headers, text headers, and trace information are displayed in the right panel
   - Click on field names to see descriptions
   - Navigate between traces using the trace selection controls

4. **Export Data**
   - **Save Plot**: Export the current plot as PNG
   - **Save Info**: Export header information to a text file
   - **Save Shapefile**: Export navigation coordinates as shapefiles
   - **Batch Process**: Process multiple files at once

### Batch Processing

1. Click the "Batch Process" button
2. Select multiple SEGY files to process
3. Choose an output directory
4. The application will:
   - Generate a plot for each file
   - Create point and line shapefiles for navigation data
   - Save header information to text files
   - Create combined shapefiles (`SEGY_Combined_Nav_points.shp` and `SEGY_Combined_Nav_line.shp`) if multiple files are processed

### Shapefile Output

Shapefiles include:
- **Point Shapefiles**: Individual CDP points with coordinates, trace numbers, and date/time
- **Line Shapefiles**: Connected navigation lines with start/end date/time
- **Coordinate Systems**: Automatically set to EPSG:4326 (WGS84) for geographic coordinates
- **Date/Time Fields**: Extracted from trace headers (YearDataRecorded, DayOfYear, HourOfDay, etc.)

## Building the Executable

To build a Windows executable:

1. Install PyInstaller:
```bash
pip install pyinstaller
```

2. Run the build script:
```bash
python build_segy_gui.py
```

The executable will be created in the `dist/` directory with the name `CCOM_SEGY_Viewer_v{VERSION}.exe`.

## Configuration

The application saves user preferences in `segy_config.json`:
- Last opened directory
- Last save directory
- Preferred colormap
- Clip percentile setting
- Window geometry

## Version History

- **v2025.05**: Added batch processing, date/time fields in shapefiles, coordinate conversion improvements
- **v2025.04**: Added ability to save full resolution plots and shapefiles

## Author

Paul Johnson  
pjohnson@ccom.unh.edu  
UNH/CCOM-JHC

## License

[Specify your license here]

## Acknowledgments

Developed at the University of New Hampshire, Center for Coastal and Ocean Mapping - Joint Hydrographic Center (UNH/CCOM-JHC).

## Support

For issues, questions, or contributions, please open an issue on the [GitHub repository](https://github.com/seamapper/SEGY_Viewer).

