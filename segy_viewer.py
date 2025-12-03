#!/usr/bin/env python3

import sys
import re
import os
import json
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import segyio
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QFileDialog, QTextEdit, 
                             QLabel, QSplitter, QMessageBox, QProgressBar,
                             QProgressDialog, QGroupBox, QGridLayout, QSpinBox, QDoubleSpinBox, QComboBox,
                             QCheckBox, QLineEdit, QDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap

"""
UNH/CCOM-JHC SEG-Y File Viewer
A Python application to view SEGY files, .

Program by Paul Johnson, pjohnson@ccom.unh.edu
Date: 2025-09-12

Center for Coastal and Ocean Mapping/Joint Hydrographic Center, University of New Hampshire

This program was developed at the University of New Hampshire, Center for Coastal and Ocean Mapping - Joint Hydrographic Center (UNH/CCOM-JHC) under the grant NA20NOS4000196 from the National Oceanic and Atmospheric Administration (NOAA).

This software is released for general use under the BSD 3-Clause License.

"""

# __version__ = "2025.04"  #Added ability to save full resolution plots and shapefiles
# __version__ = "2025.05"  #Add batch processing of SEGY files
# __version__ = "2025.06"  # Changes to layout and batch mode
__version__ = "2025.07"  # Added license information and updated README.md

class SegyConfig:
    """Configuration management for SEGY GUI settings"""
    
    def __init__(self, config_file='segy_config.json'):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self):
        """Load configuration from file or create default"""
        default_config = {
            'last_open_directory': '',
            'last_save_directory': '',
            'last_colormap': 'BuPu',
            'last_clip_percentile': 99,
            'window_geometry': None
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    # Merge with defaults to handle missing keys
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
        except Exception as e:
            print(f"Warning: Could not load config file: {e}")
        
        return default_config
    
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save config file: {e}")
    
    def get(self, key, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """Set configuration value"""
        self.config[key] = value
        self.save_config()
    
    def update_last_open_directory(self, directory):
        """Update last open directory"""
        if directory and os.path.isdir(directory):
            self.set('last_open_directory', directory)
    
    def update_last_save_directory(self, directory):
        """Update last save directory"""
        if directory and os.path.isdir(directory):
            self.set('last_save_directory', directory)
    
    def update_colormap(self, colormap):
        """Update last used colormap"""
        self.set('last_colormap', colormap)
    
    def update_clip_percentile(self, percentile):
        """Update last used clip percentile"""
        self.set('last_clip_percentile', percentile)


class SegyLoaderThread(QThread):
    """Thread for loading SEGY files to prevent GUI freezing"""
    progress = pyqtSignal(int)
    finished = pyqtSignal(object, object, object, object, object)  # data, headers, text_headers, bin_headers, file_info
    error = pyqtSignal(str)
    
    def __init__(self, filename):
        super().__init__()
        self.filename = filename
    
    def run(self):
        try:
            self.progress.emit(10)
            
            with segyio.open(self.filename, ignore_geometry=True, strict=False) as f:
                self.progress.emit(30)
                
                # Get basic attributes
                n_traces = f.tracecount
                sample_rate = segyio.tools.dt(f) / 1000
                n_samples = f.samples.size
                twt = f.samples
                
                self.progress.emit(50)
                
                # Load data (this might be memory intensive for large files)
                data = f.trace.raw[:]
                
                self.progress.emit(70)
                
                # Load headers
                bin_headers = f.bin
                text_headers = self.parse_text_header(f)
                trace_headers = self.parse_trace_headers(f, n_traces)
                
                self.progress.emit(90)
                
                # File information
                file_info = {
                    'filename': os.path.basename(self.filename),
                    'n_traces': n_traces,
                    'n_samples': n_samples,
                    'sample_rate': sample_rate,
                    'twt': twt
                }
                
                self.progress.emit(100)
                self.finished.emit(data, trace_headers, text_headers, bin_headers, file_info)
                
        except Exception as e:
            error_msg = str(e)
            # Provide more helpful error messages for common issues
            if "trace count inconsistent" in error_msg or "non-uniform" in error_msg:
                error_msg = f"""SEGY File Format Issue

The file '{os.path.basename(self.filename)}' cannot be opened because it has structural problems:

• Trace count inconsistent with file size
• Trace lengths are non-uniform (not standard SEGY format)

This typically indicates:
1. The file is corrupted or incomplete
2. The file was not properly written
3. The file uses a non-standard SEGY variant

Possible solutions:
• Try opening the file with specialized SEGY repair tools
• Contact the data provider for a corrected version
• Use alternative SEGY viewers that handle non-standard formats

Original error: {error_msg}"""
            elif "strict" in error_msg.lower():
                error_msg = f"SEGY file format issue:\n\n{error_msg}\n\nThe file may not conform to strict SEGY standards but could still be readable."
            self.error.emit(error_msg)
    
    def parse_trace_headers(self, segyfile, n_traces):
        """Parse the segy file trace headers into a pandas dataframe."""
        headers = segyio.tracefield.keys
        df = pd.DataFrame(index=range(1, n_traces + 1), columns=headers.keys())
        for k, v in headers.items():
            df[k] = segyfile.attributes(v)[:]
        return df
    
    def parse_text_header(self, segyfile):
        """Format segy text header into a readable, clean dict"""
        try:
            raw_header = segyio.tools.wrap(segyfile.text[0])
            cut_header = re.split(r'C ', raw_header)[1::]
            text_header = [x.replace('\n', ' ') for x in cut_header]
            
            # Check if we have any text header content
            if not text_header:
                return {"C01": "No text header found or unsupported format"}
            
            # Remove last 2 characters from the last item if it exists
            if text_header[-1]:
                text_header[-1] = text_header[-1][:-2]
            
            clean_header = {}
            i = 1
            for item in text_header:
                key = "C" + str(i).rjust(2, '0')
                i += 1
                clean_header[key] = item
            return clean_header
        except Exception as e:
            # Return a fallback header if parsing fails
            return {"C01": f"Text header parsing failed: {str(e)}"}


class SegyPlotWidget(FigureCanvas):
    """Custom matplotlib widget for SEGY plotting"""
    
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(12, 6))
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self.data = None
        self.file_info = None
        self.colorbar = None  # Store reference to colorbar
        self.selected_trace_line = None  # Store reference to selected trace line
        self.trace_headers = None  # Store trace headers for lookup
        self.trace_callback = None  # Callback function for trace selection
        
        # Connect mouse click event
        self.mpl_connect('button_press_event', self.on_click)
        
    def plot_segy_data(self, data, file_info, trace_headers=None, clip_percentile=99, colormap='BuPu', depth_mode=False, velocity=1500.0, clip_enabled=True, std_dev_enabled=False, std_dev_value=2.0):
        """Plot SEGY data"""
        self.data = data
        self.file_info = file_info
        self.trace_headers = trace_headers
        
        # Clear the entire figure to avoid colorbar issues
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self.colorbar = None
        self.selected_trace_line = None
        
        # Apply standard deviation clipping if enabled
        plot_data = data.copy()
        if std_dev_enabled:
            plot_data = self._apply_std_dev_clipping(plot_data, std_dev_value)
        
        # Calculate amplitude clipping
        if clip_enabled:
            vm = np.percentile(plot_data, clip_percentile)
            vm0 = 0
            vm1 = vm
        else:
            # No clipping - use full data range
            vm0 = plot_data.min()
            vm1 = plot_data.max()
            vm = vm1  # Set vm for return value
        
        # Create extent for proper axis labeling
        n_traces = file_info['n_traces']
        twt = file_info['twt']
        
        # Convert TWT to depth if depth mode is enabled
        if depth_mode:
            # Convert TWT (ms) to depth (m): Depth = (TWT_ms / 1000) × Velocity_m/s / 2
            depth = (twt / 1000.0) * velocity / 2.0
            y_min = depth[-1]  # Last depth value (deepest)
            y_max = depth[0]   # First depth value (shallowest)
            y_label = 'Depth [m]'
        else:
            y_min = twt[-1]  # Last TWT value (deepest)
            y_max = twt[0]   # First TWT value (shallowest)
            y_label = 'TWT [ms]'
        
        extent = [1, n_traces, y_min, y_max]
        
        # Plot the data
        im = self.ax.imshow(plot_data.T, cmap=colormap, vmin=vm0, vmax=vm1, 
                           aspect='auto', extent=extent)
        
        # Set labels and title
        self.ax.set_xlabel('CDP number')
        self.ax.set_ylabel(y_label)
        self.ax.set_title(f'{file_info["filename"]}')
        
        # Add colorbar with reduced padding
        self.colorbar = self.fig.colorbar(im, ax=self.ax, label='Amplitude', pad=0.02)
        
        # Reduce plot margins to maximize plot area
        self.fig.subplots_adjust(left=0.08, bottom=0.10, right=1.00, top=0.95)
        
        # Refresh the canvas
        self.draw()
        
        return vm, vm1
    
    def _apply_std_dev_clipping(self, data, std_dev_value):
        """Apply standard deviation clipping to the data"""
        # Calculate mean and standard deviation
        mean = np.mean(data)
        std = np.std(data)
        
        # Calculate clipping limits: mean ± (std_dev_value * std)
        lower_limit = mean - (std_dev_value * std)
        upper_limit = mean + (std_dev_value * std)
        
        # Clip the data to these limits
        clipped_data = np.clip(data, lower_limit, upper_limit)
        
        return clipped_data
    
    def on_click(self, event):
        """Handle mouse click events on the plot - middle button for trace selection"""
        # Only process middle mouse button clicks (button 2) for trace selection
        if event.button != 2:
            return
        
        if event.inaxes != self.ax or self.data is None:
            return
        
        # Get the clicked coordinates
        x_click = event.xdata
        y_click = event.ydata
        
        if x_click is None or y_click is None:
            return
        
        # Convert x coordinate to trace number (CDP number)
        trace_number = int(round(x_click))
        
        # Validate trace number
        if trace_number < 1 or trace_number > self.file_info['n_traces']:
            return
        
        # Update visual feedback
        self.update_selected_trace(trace_number)
        
        # Call the callback function if it exists
        if self.trace_callback:
            self.trace_callback(trace_number)
    
    def update_selected_trace(self, trace_number):
        """Update the visual indicator for the selected trace"""
        # Remove existing line if it exists
        if self.selected_trace_line:
            self.selected_trace_line.remove()
            self.selected_trace_line = None
        
        # Add new vertical line at the selected trace
        twt = self.file_info['twt']
        self.selected_trace_line = self.ax.axvline(x=trace_number, color='red', 
                                                  linewidth=2, alpha=0.8, linestyle='--')
        
        # Refresh the canvas
        self.draw()
    
    def set_trace_callback(self, callback):
        """Set the callback function to be called when a trace is selected"""
        self.trace_callback = callback
    
    def save_plot(self, filename, full_resolution=False):
        """Save the current plot to file"""
        if self.data is not None:
            if full_resolution:
                # Full resolution export - match the interactive plot exactly
                # Get current plot settings from the GUI
                from PyQt6.QtWidgets import QApplication
                main_window = QApplication.instance().activeWindow()
                
                # Get current settings
                clip_percentile = main_window.clip_spinbox.value()
                colormap = main_window.colormap_combo.currentText()
                depth_mode = main_window.depth_mode_checkbox.isChecked()
                velocity = main_window.velocity_spinbox.value()
                clip_enabled = main_window.clip_checkbox.isChecked()
                std_dev_enabled = main_window.std_dev_checkbox.isChecked()
                std_dev_value = main_window.std_dev_spinbox.value()
                
                # Apply standard deviation clipping if enabled
                plot_data = self.data.copy()
                if std_dev_enabled:
                    plot_data = self._apply_std_dev_clipping(plot_data, std_dev_value)
                
                # Calculate amplitude clipping (same as interactive plot)
                if clip_enabled:
                    vm = np.percentile(plot_data, clip_percentile)
                    vm0 = 0
                    vm1 = vm
                else:
                    # No clipping - use full data range
                    vm0 = plot_data.min()
                    vm1 = plot_data.max()
                
                # Create extent for proper axis labeling (same as interactive plot)
                n_traces = self.file_info['n_traces']
                twt = self.file_info['twt']
                
                # Convert TWT to depth if depth mode is enabled
                if depth_mode:
                    # Convert TWT (ms) to depth (m): Depth = (TWT_ms / 1000) × Velocity_m/s / 2
                    depth = (twt / 1000.0) * velocity / 2.0
                    y_min = depth[-1]  # Last depth value (deepest)
                    y_max = depth[0]   # First depth value (shallowest)
                    y_label = 'Depth [m]'
                else:
                    y_min = twt[-1]  # Last TWT value (deepest)
                    y_max = twt[0]   # First TWT value (shallowest)
                    y_label = 'TWT [ms]'
                
                extent = [1, n_traces, y_min, y_max]
                
                # Calculate figure size based on data dimensions
                data_shape = self.data.shape
                fig_width = max(12, data_shape[1] * 0.01)  # Scale width by number of traces
                fig_height = max(8, data_shape[0] * 0.002)  # Scale height by number of samples
                
                # Create a new figure for full resolution export
                import matplotlib.pyplot as plt
                fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=300)
                
                # Plot the full data with same settings as interactive plot
                im = ax.imshow(plot_data.T, cmap=colormap, vmin=vm0, vmax=vm1, 
                              aspect='auto', extent=extent)
                
                # Add labels and title (same as interactive plot)
                ax.set_xlabel('CDP number')
                ax.set_ylabel(y_label)
                ax.set_title(f'{self.file_info["filename"]} (Full Resolution)')
                
                # Add colorbar (same as interactive plot)
                plt.colorbar(im, ax=ax, label='Amplitude')
                
                # Save with high quality settings
                fig.savefig(filename, dpi=300, bbox_inches='tight', 
                           facecolor='white', edgecolor='none')
                plt.close(fig)  # Close the figure to free memory
            else:
                # Normal export - use current display
                self.fig.savefig(filename, dpi=300, bbox_inches='tight')


class ClickableTextEdit(QTextEdit):
    """Custom QTextEdit that handles clicks on field names"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_gui = parent
    
    def mousePressEvent(self, event):
        """Handle mouse press events to detect clicks on field names"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Get the cursor position and check if it's over a link
            cursor = self.cursorForPosition(event.pos())
            cursor.select(cursor.SelectionType.WordUnderCursor)
            selected_text = cursor.selectedText()
            
            # Check if the selected text is a field name
            clickable_fields = ['JobID', 'LineNumber', 'ReelNumber', 'Traces', 'AuxTraces', 
                              'Interval', 'IntervalOriginal', 'Samples', 'SamplesOriginal', 
                              'Format', 'EnsembleFold', 'SortingCode', 'VerticalSum', 
                              'SweepFrequencyStart', 'SweepFrequencyEnd', 'SweepLength', 
                              'Sweep', 'SweepChannel', 'SweepTaperStart', 'SweepTaperEnd', 
                              'Taper', 'CorrelatedTraces', 'BinaryGainRecovery', 
                              'AmplitudeRecovery', 'MeasurementSystem', 'ImpulseSignalPolarity', 
                              'VibratoryPolarity', 'ExtAuxTraces', 'ExtSamples', 
                              'ExtSamplesOriginal', 'ExtEnsembleFold', 'SEGYRevision', 
                              'SEGYRevisionMinor', 'TraceFlag', 'ExtendedHeaders',
                              'MaxAdditionalTraceHeaders', 'TimeBasis', 'AdditionalTraceHeaderBytes',
                              'ByteOffset', 'AdditionalTraceHeaderSamples']
            
            # Trace header fields
            trace_header_fields = ['TRACE_SEQUENCE_LINE', 'TRACE_SEQUENCE_FILE', 'FieldRecord', 
                                 'TraceNumber', 'EnergySourcePoint', 'CDP', 'CDP_TRACE', 
                                 'TraceIdentificationCode', 'NSummedTraces', 'NStackedTraces', 
                                 'DataUse', 'offset', 'ReceiverGroupElevation', 'SourceSurfaceElevation', 
                                 'SourceDepth', 'ReceiverDatumElevation', 'SourceDatumElevation', 
                                 'SourceWaterDepth', 'GroupWaterDepth', 'ElevationScalar', 
                                 'SourceGroupScalar', 'SourceX', 'SourceY', 'GroupX', 'GroupY', 
                                 'CoordinateUnits', 'WeatheringVelocity', 'SubWeatheringVelocity', 
                                 'SourceUpholeTime', 'GroupUpholeTime', 'SourceStaticCorrection', 
                                 'GroupStaticCorrection', 'TotalStaticApplied', 'LagTimeA', 'LagTimeB', 
                                 'DelayRecordingTime', 'MuteTimeStart', 'MuteTimeEND', 
                                 'TRACE_SAMPLE_COUNT', 'TRACE_SAMPLE_INTERVAL', 'GainType', 
                                 'InstrumentGainConstant', 'InstrumentInitialGain', 'Correlated', 
                                 'SweepFrequencyStart', 'SweepFrequencyEnd', 'SweepLength', 
                                 'SweepType', 'SweepTraceTaperLengthStart', 'SweepTraceTaperLengthEnd', 
                                 'TaperType', 'AliasFilterFrequency', 'AliasFilterSlope', 
                                 'NotchFilterFrequency', 'NotchFilterSlope', 'LowCutFrequency', 
                                 'HighCutFrequency', 'LowCutSlope', 'HighCutSlope', 'YearDataRecorded', 
                                 'DayOfYear', 'HourOfDay', 'MinuteOfHour', 'SecondOfMinute', 
                                 'TimeBaseCode', 'TraceWeightingFactor', 'GeophoneGroupNumberRoll1', 
                                 'GeophoneGroupNumberFirstTraceOrigField', 'GeophoneGroupNumberLastTraceOrigField', 
                                 'GapSize', 'OverTravel', 'CDP_X', 'CDP_Y', 'INLINE_3D', 'CROSSLINE_3D', 
                                 'ShotPoint', 'ShotPointScalar', 'TraceValueMeasurementUnit']
            
            all_clickable_fields = clickable_fields + trace_header_fields
            
            if selected_text in all_clickable_fields and self.parent_gui:
                if selected_text in trace_header_fields:
                    self.parent_gui.show_trace_field_description(selected_text)
                else:
                    self.parent_gui.show_field_description(selected_text)
                return
        
        super().mousePressEvent(event)


class SegyGui(QMainWindow):
    """Main GUI window for SEGY file viewer"""
    
    def __init__(self):
        super().__init__()
        self.config = SegyConfig()
        self.current_data = None
        self.current_headers = None
        self.current_text_headers = None
        self.current_bin_headers = None
        self.current_file_info = None
        self.current_trace_number = 1  # Track current selected trace
        self.show_byte_locations = False  # Track byte location display state
        self.depth_mode = False  # Track if depth mode is enabled
        self.velocity = 1500.0  # Default velocity in m/s
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle(f'UNH/CCOM-JHC SEG-Y File Viewer v{__version__} - pjohnson@ccom.unh.edu')
        self.setGeometry(100, 100, 1400, 900)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Create controls panel
        controls_panel = self.create_controls_panel()
        main_layout.addWidget(controls_panel)
        
        # Create splitter for main content
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Create plot widget container with toolbar
        plot_container = QWidget()
        plot_layout = QVBoxLayout(plot_container)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create plot widget
        self.plot_widget = SegyPlotWidget()
        self.plot_widget.set_trace_callback(self.on_trace_selected)
        plot_layout.addWidget(self.plot_widget)
        
        # Create navigation toolbar for zoom and pan
        self.plot_toolbar = NavigationToolbar(self.plot_widget, self)
        plot_layout.addWidget(self.plot_toolbar)
        
        splitter.addWidget(plot_container)
        
        # Create headers panel
        headers_panel = self.create_headers_panel()
        headers_panel.setMaximumWidth(490)  # Prevent headers panel from expanding beyond 490 pixels
        splitter.addWidget(headers_panel)
        
        # Set splitter proportions (65% plot, 35% headers) to accommodate both header panels
        splitter.setSizes([910, 490])
        
        # Create status bar
        self.statusBar().showMessage('Ready - Select a SEGY file to begin')
        
        # Add About button to status bar
        about_button = QPushButton("About this Program")
        about_button.setMaximumHeight(25)
        about_button.clicked.connect(self.show_about_dialog)
        self.statusBar().addPermanentWidget(about_button)
        
    def create_controls_panel(self):
        """Create the controls panel with file selection and plot options"""
        group = QGroupBox("File Control")
        group.setMaximumHeight(80)  # Limit the height of the controls panel
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 5, 10, 5)  # Reduce margins for more compact layout
        
        # File selection
        self.file_button = QPushButton("Open SEGY File")
        self.file_button.clicked.connect(self.open_file)
        self.file_button.setMaximumHeight(30)  # Make button more compact
        layout.addWidget(self.file_button)
        
        # File info label
        self.file_label = QLabel("No file selected")
        self.file_label.setStyleSheet("color: gray; font-style: italic;")
        self.file_label.setMaximumHeight(30)  # Make label more compact
        layout.addWidget(self.file_label)
        
        layout.addStretch()
        
        # Save plot button
        self.save_button = QPushButton("Save Plot")
        self.save_button.clicked.connect(self.save_plot)
        self.save_button.setEnabled(False)
        self.save_button.setMaximumHeight(30)
        layout.addWidget(self.save_button)
        
        # Full resolution checkbox
        self.full_res_checkbox = QCheckBox("Full Res")
        self.full_res_checkbox.setChecked(True)  # On by default
        self.full_res_checkbox.setEnabled(False)  # Disabled until file is loaded
        self.full_res_checkbox.setMaximumHeight(30)
        layout.addWidget(self.full_res_checkbox)
        
        # Save info button
        self.save_info_button = QPushButton("Save Info")
        self.save_info_button.clicked.connect(self.save_header_info)
        self.save_info_button.setEnabled(False)
        self.save_info_button.setMaximumHeight(30)
        layout.addWidget(self.save_info_button)
        
        # Save shapefile button
        self.save_shapefile_button = QPushButton("Save Shapefile")
        self.save_shapefile_button.clicked.connect(self.save_shapefile)
        self.save_shapefile_button.setEnabled(False)
        self.save_shapefile_button.setMaximumHeight(30)
        layout.addWidget(self.save_shapefile_button)
        
        # Batch process button
        self.batch_process_button = QPushButton("Batch Process")
        self.batch_process_button.clicked.connect(self.batch_process)
        self.batch_process_button.setMaximumHeight(30)  # Make button more compact
        layout.addWidget(self.batch_process_button)
        
        return group
    
    def create_headers_panel(self):
        """Create the headers information panel"""
        # Main container for both header panels
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        
        # Plot Control panel
        plot_control_group = QGroupBox("Plot Control")
        plot_control_layout = QVBoxLayout(plot_control_group)
        
        # First row: Depth and Velocity
        row1_layout = QHBoxLayout()
        
        # Depth mode toggle (enabled from start for batch processing)
        self.depth_mode_checkbox = QCheckBox("Depth")
        self.depth_mode_checkbox.setMaximumHeight(30)
        self.depth_mode_checkbox.setChecked(False)
        self.depth_mode_checkbox.stateChanged.connect(self.on_depth_mode_changed)
        row1_layout.addWidget(self.depth_mode_checkbox)
        
        # Velocity parameter (enabled from start for batch processing)
        velocity_label = QLabel("Velocity (m/s):")
        velocity_label.setMaximumHeight(30)
        row1_layout.addWidget(velocity_label)
        
        self.velocity_spinbox = QSpinBox()
        self.velocity_spinbox.setRange(1000, 5000)
        self.velocity_spinbox.setValue(1500)
        self.velocity_spinbox.setMaximumHeight(30)
        self.velocity_spinbox.setMaximumWidth(80)
        self.velocity_spinbox.valueChanged.connect(self.on_velocity_changed)
        row1_layout.addWidget(self.velocity_spinbox)
        
        row1_layout.addStretch()  # Add stretch to push controls to the left
        plot_control_layout.addLayout(row1_layout)
        
        # Second row: Clip checkbox and Percent (%)
        row2_layout = QHBoxLayout()
        
        # Clip checkbox
        self.clip_checkbox = QCheckBox("Clip")
        self.clip_checkbox.setMaximumHeight(30)
        self.clip_checkbox.setChecked(True)  # On by default
        self.clip_checkbox.stateChanged.connect(self.on_clip_enabled_changed)
        row2_layout.addWidget(self.clip_checkbox)
        
        # Clip % parameter
        clip_label = QLabel("%:")
        clip_label.setMaximumHeight(30)
        row2_layout.addWidget(clip_label)
        
        self.clip_spinbox = QSpinBox()
        self.clip_spinbox.setRange(50, 100)
        self.clip_spinbox.setValue(self.config.get('last_clip_percentile', 99))
        self.clip_spinbox.setMaximumHeight(30)
        self.clip_spinbox.setMaximumWidth(60)
        # Connect clip percentile change to automatic plot update
        self.clip_spinbox.valueChanged.connect(self.on_clip_percentile_changed)
        row2_layout.addWidget(self.clip_spinbox)
        
        # Standard Deviation checkbox and parameter
        self.std_dev_checkbox = QCheckBox("Standard Deviation")
        self.std_dev_checkbox.setMaximumHeight(30)
        self.std_dev_checkbox.setChecked(False)  # Off by default
        self.std_dev_checkbox.stateChanged.connect(self.on_std_dev_enabled_changed)
        row2_layout.addWidget(self.std_dev_checkbox)
        
        std_dev_label = QLabel("Value:")
        std_dev_label.setMaximumHeight(30)
        row2_layout.addWidget(std_dev_label)
        
        self.std_dev_spinbox = QDoubleSpinBox()
        self.std_dev_spinbox.setRange(0.1, 10.0)
        self.std_dev_spinbox.setValue(2.0)
        self.std_dev_spinbox.setSingleStep(0.1)
        self.std_dev_spinbox.setDecimals(1)
        self.std_dev_spinbox.setMaximumHeight(30)
        self.std_dev_spinbox.setMaximumWidth(60)
        self.std_dev_spinbox.valueChanged.connect(self.on_std_dev_changed)
        row2_layout.addWidget(self.std_dev_spinbox)
        
        row2_layout.addStretch()  # Add stretch to push controls to the left
        plot_control_layout.addLayout(row2_layout)
        
        # Third row: Colormap
        row3_layout = QHBoxLayout()
        
        # Colormap parameter
        colormap_label = QLabel("Colormap:")
        colormap_label.setMaximumHeight(30)
        row3_layout.addWidget(colormap_label)
        
        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(['BuPu', 'RdBu', 'seismic', 'gray', 'viridis', 'plasma'])
        self.colormap_combo.setMaximumHeight(30)
        self.colormap_combo.setMaximumWidth(100)
        # Set the saved colormap
        saved_colormap = self.config.get('last_colormap', 'BuPu')
        index = self.colormap_combo.findText(saved_colormap)
        if index >= 0:
            self.colormap_combo.setCurrentIndex(index)
        # Connect colormap change to automatic plot update
        self.colormap_combo.currentTextChanged.connect(self.on_colormap_changed)
        row3_layout.addWidget(self.colormap_combo)
        
        # Update plot button
        self.update_button = QPushButton("Update Plot")
        self.update_button.setMaximumHeight(30)
        self.update_button.clicked.connect(self.update_plot)
        self.update_button.setEnabled(False)  # Disabled until file is loaded
        row3_layout.addWidget(self.update_button)
        
        row3_layout.addStretch()  # Add stretch to push controls to the left
        plot_control_layout.addLayout(row3_layout)
        
        main_layout.addWidget(plot_control_group)
        
        # Header Information panel
        header_group = QGroupBox("Header Information")
        header_layout = QVBoxLayout(header_group)
        
        self.headers_text = ClickableTextEdit(self)
        self.headers_text.setReadOnly(True)
        self.headers_text.setFont(QFont("Courier", 9))
        header_layout.addWidget(self.headers_text)
        
        main_layout.addWidget(header_group)
        
        # Trace Info panel (merged Trace Selection and Trace Information)
        trace_info_group = QGroupBox("Trace Info")
        trace_info_layout = QVBoxLayout(trace_info_group)
        
        # Trace Selection controls (top section)
        # Instruction text
        instruction_label = QLabel("Middle Button click on plot to select trace")
        instruction_label.setStyleSheet("color: gray; font-style: italic; font-size: 9pt;")
        instruction_label.setMaximumHeight(20)
        trace_info_layout.addWidget(instruction_label)
        
        # Controls layout
        controls_layout = QHBoxLayout()
        
        # Back button
        self.trace_back_button = QPushButton("◀ Back")
        self.trace_back_button.setMaximumHeight(30)
        self.trace_back_button.setMaximumWidth(60)
        self.trace_back_button.clicked.connect(self.trace_back)
        self.trace_back_button.setEnabled(False)
        controls_layout.addWidget(self.trace_back_button)
        
        # Trace number input
        trace_label = QLabel("CDP:")
        trace_label.setMaximumHeight(30)
        controls_layout.addWidget(trace_label)
        
        self.trace_number_input = QLineEdit()
        self.trace_number_input.setMaximumHeight(30)
        self.trace_number_input.setMaximumWidth(80)
        self.trace_number_input.setPlaceholderText("1")
        self.trace_number_input.returnPressed.connect(self.on_trace_number_entered)
        controls_layout.addWidget(self.trace_number_input)
        
        # Forward button
        self.trace_forward_button = QPushButton("Forward ▶")
        self.trace_forward_button.setMaximumHeight(30)
        self.trace_forward_button.setMaximumWidth(70)
        self.trace_forward_button.clicked.connect(self.trace_forward)
        self.trace_forward_button.setEnabled(False)
        controls_layout.addWidget(self.trace_forward_button)
        
        # Go button
        self.trace_go_button = QPushButton("Go")
        self.trace_go_button.setMaximumHeight(30)
        self.trace_go_button.setMaximumWidth(40)
        self.trace_go_button.clicked.connect(self.on_trace_number_entered)
        self.trace_go_button.setEnabled(False)
        controls_layout.addWidget(self.trace_go_button)
        
        # Byte location checkbox
        self.byte_loc_checkbox = QCheckBox("Byte Loc")
        self.byte_loc_checkbox.setMaximumHeight(30)
        self.byte_loc_checkbox.setChecked(False)  # Off by default
        self.byte_loc_checkbox.stateChanged.connect(self.on_byte_loc_changed)
        controls_layout.addWidget(self.byte_loc_checkbox)
        
        controls_layout.addStretch()  # Add stretch to push buttons to the left
        trace_info_layout.addLayout(controls_layout)
        
        # Trace Information (bottom section)
        self.trace_info_text = ClickableTextEdit(self)
        self.trace_info_text.setReadOnly(True)
        self.trace_info_text.setFont(QFont("Courier", 9))
        self.trace_info_text.setPlaceholderText("Click on the plot to view trace header information...")
        trace_info_layout.addWidget(self.trace_info_text)
        
        main_layout.addWidget(trace_info_group)
        
        # Status area for field descriptions
        status_group = QGroupBox("Field Description")
        status_layout = QVBoxLayout(status_group)
        
        self.field_description_text = QTextEdit()
        self.field_description_text.setReadOnly(True)
        self.field_description_text.setFont(QFont("Arial", 9))
        self.field_description_text.setPlaceholderText("Click on a binary header field name to see its description...")
        status_layout.addWidget(self.field_description_text)
        
        main_layout.addWidget(status_group)
        
        return main_widget
    
    def open_file(self):
        """Open file dialog and load SEGY file"""
        last_dir = self.config.get('last_open_directory', '')
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open SEGY File", last_dir, "SEGY Files (*.sgy *.segy);;All Files (*)"
        )
        
        if filename:
            # Update last open directory
            self.config.update_last_open_directory(os.path.dirname(filename))
            self.load_segy_file(filename)
    
    def load_segy_file(self, filename):
        """Load SEGY file in a separate thread"""
        self.file_label.setText(f"Loading: {os.path.basename(filename)}...")
        self.file_button.setEnabled(False)
        
        # Create and start loading thread
        self.loader_thread = SegyLoaderThread(filename)
        self.loader_thread.progress.connect(self.update_progress)
        self.loader_thread.finished.connect(self.on_file_loaded)
        self.loader_thread.error.connect(self.on_load_error)
        self.loader_thread.start()
        
        # Show progress bar
        self.progress_bar = QProgressBar()
        self.statusBar().addWidget(self.progress_bar)
    
    def update_progress(self, value):
        """Update progress bar"""
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setValue(value)
    
    def on_file_loaded(self, data, trace_headers, text_headers, bin_headers, file_info):
        """Handle successful file loading"""
        self.current_data = data
        self.current_headers = trace_headers
        self.current_text_headers = text_headers
        self.current_bin_headers = bin_headers
        self.current_file_info = file_info
        
        # Update UI
        self.file_label.setText(f"Loaded: {file_info['filename']}")
        self.file_button.setEnabled(True)
        self.update_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.full_res_checkbox.setEnabled(True)
        # depth_mode_checkbox and velocity_spinbox are always enabled (for batch processing)
        self.save_info_button.setEnabled(True)
        self.save_shapefile_button.setEnabled(True)
        
        # Remove progress bar
        if hasattr(self, 'progress_bar'):
            self.statusBar().removeWidget(self.progress_bar)
            del self.progress_bar
        
        # Update headers display
        self.update_headers_display()
        
        # Create initial plot
        self.update_plot()
        
        self.statusBar().showMessage(f"File loaded: {file_info['n_traces']} traces, {file_info['n_samples']} samples")
        
        # Enable trace selection controls and show first trace
        self.enable_trace_selection()
        self.select_trace(1)  # Default to first CDP
    
    def enable_trace_selection(self):
        """Enable trace selection controls when file is loaded"""
        self.trace_back_button.setEnabled(True)
        self.trace_forward_button.setEnabled(True)
        self.trace_go_button.setEnabled(True)
        self.trace_number_input.setEnabled(True)
    
    def trace_back(self):
        """Navigate to the previous trace"""
        if self.current_trace_number > 1:
            self.select_trace(self.current_trace_number - 1)
    
    def trace_forward(self):
        """Navigate to the next trace"""
        if self.current_file_info and self.current_trace_number < self.current_file_info['n_traces']:
            self.select_trace(self.current_trace_number + 1)
    
    def on_trace_number_entered(self):
        """Handle trace number input from text field"""
        try:
            trace_number = int(self.trace_number_input.text())
            self.select_trace(trace_number)
        except ValueError:
            # Invalid input, reset to current trace
            self.trace_number_input.setText(str(self.current_trace_number))
    
    def select_trace(self, trace_number):
        """Select a specific trace and update all displays"""
        if not self.current_file_info:
            return
        
        # Validate trace number
        if trace_number < 1 or trace_number > self.current_file_info['n_traces']:
            return
        
        self.current_trace_number = trace_number
        
        # Update the input field
        self.trace_number_input.setText(str(trace_number))
        
        # Update navigation buttons
        self.trace_back_button.setEnabled(trace_number > 1)
        self.trace_forward_button.setEnabled(trace_number < self.current_file_info['n_traces'])
        
        # Update visual feedback on plot
        if hasattr(self, 'plot_widget') and self.plot_widget:
            self.plot_widget.update_selected_trace(trace_number)
        
        # Update trace information display
        self.display_trace_info(trace_number)
    
    def on_byte_loc_changed(self, state):
        """Handle byte location checkbox state change"""
        self.show_byte_locations = state == Qt.CheckState.Checked.value
        # Refresh the current trace display if data is loaded
        if self.current_data is not None:
            self.display_trace_info(self.current_trace_number)
    
    def on_binary_desc_changed(self, state):
        """Handle binary header descriptions checkbox state change - DEPRECATED: Headers are always expanded now"""
        # This method is kept for compatibility but no longer needed
        # Headers are always expanded
        if self.current_data is not None:
            self.update_headers_display()
    
    def show_field_description(self, field_name):
        """Show description for a binary header field"""
        decoder = self.get_binary_header_decoder()
        
        # Map segyio field names to decoder keys
        field_mappings = {
            'JobID': 'JobIdentificationNumber',
            'LineNumber': 'LineNumber',
            'ReelNumber': 'ReelNumber',
            'Traces': 'NumberOfDataTracesPerRecord',
            'AuxTraces': 'NumberOfAuxiliaryTracesPerRecord',
            'Interval': 'SampleIntervalInMicroseconds',
            'IntervalOriginal': 'SampleIntervalInMicrosecondsOfOriginalFieldRecording',
            'Samples': 'NumberOfSamplesPerDataTrace',
            'SamplesOriginal': 'NumberOfSamplesPerDataTraceForOriginalFieldRecording',
            'Format': 'DataSampleFormat',
            'EnsembleFold': 'EnsembleFold',
            'SortingCode': 'TraceSortingCode',
            'VerticalSum': 'VerticalSumCode',
            'SweepFrequencyStart': 'SweepFrequencyAtStart',
            'SweepFrequencyEnd': 'SweepFrequencyAtEnd',
            'SweepLength': 'SweepLengthInMilliseconds',
            'Sweep': 'SweepTypeCode',
            'SweepChannel': 'SweepChannelNumber',
            'SweepTaperStart': 'SweepTraceTaperLengthAtStartInMilliseconds',
            'SweepTaperEnd': 'SweepTraceTaperLengthAtEndInMilliseconds',
            'Taper': 'TaperType',
            'CorrelatedTraces': 'CorrelatedDataTraces',
            'BinaryGainRecovery': 'BinaryGainRecovered',
            'AmplitudeRecovery': 'AmplitudeRecoveryMethod',
            'MeasurementSystem': 'MeasurementSystem',
            'ImpulseSignalPolarity': 'ImpulseSignalPolarity',
            'VibratoryPolarity': 'VibratoryPolarityCode',
            'ExtAuxTraces': 'ExtendedNumberOfAuxiliaryTracesPerRecord',
            'ExtSamples': 'ExtendedNumberOfSamplesPerDataTrace',
            'ExtSamplesOriginal': 'ExtendedNumberOfSamplesPerDataTraceForOriginalFieldRecording',
            'ExtEnsembleFold': 'ExtendedEnsembleFold',
            'SEGYRevision': 'SEGYFormatRevisionNumber',
            'SEGYRevisionMinor': 'SEGYFormatRevisionNumberMinor',
            'TraceFlag': 'FixedLengthTraceFlag',
            'ExtendedHeaders': 'NumberOfExtendedTextualFileHeaderRecords'
        }
        
        # Byte location mappings for SEG-Y Rev 2.0 (from segy_binheader.xlsx)
        byte_locations = {
            'JobID': '3201–3204: Job identification number.',
            'LineNumber': '3205–3208: Line number. For 3-D poststack data, this will typically contain the in-line number.',
            'ReelNumber': '3209–3212: Reel number.',
            'Traces': '3213–3214: Number of data traces per ensemble. Mandatory for prestack data.',
            'AuxTraces': '3215–3216: Number of auxiliary traces per ensemble. Mandatory for prestack data.',
            'Interval': '3217–3218: Sample interval. Microseconds (µs) for time data, Hertz (Hz) for frequency data, meters (m) or feet (ft) for depth data.',
            'IntervalOriginal': '3219–3220: Sample interval of original field recording. Microseconds (µs) for time data, Hertz (Hz) for frequency data, meters (m) or feet (ft) for depth data.',
            'Samples': '3221–3222: Number of samples per data trace. Note: The sample interval and number of samples in the Binary File Header should be for the primary set of seismic data traces in the file.',
            'SamplesOriginal': '3223–3224: Number of samples per data trace for original field recording.',
            'Format': '3225–3226: Data sample format code. Mandatory for all data. These formats are described in Appendix E.',
            'EnsembleFold': '3227–3228: Ensemble fold — The expected number of data traces per trace ensemble (e.g. the CMP fold).',
            'SortingCode': '3229–3230: Trace sorting code (i.e. type of ensemble)',
            'VerticalSum': '3231–3232: Vertical sum code: 1 = no sum, 2 = two sum, …, N = M–1 sum (M = 2 to 32,767)',
            'SweepFrequencyStart': '3233–3234: Sweep frequency at start (Hz).',
            'SweepFrequencyEnd': '3235–3236: Sweep frequency at end (Hz).',
            'SweepLength': '3237–3238: Sweep length (ms).',
            'Sweep': '3239–3240: Sweep type code: 1 = linear, 2 = parabolic, 3 = exponential, 4 = other',
            'SweepChannel': '3241–3242: Trace number of sweep channel.',
            'SweepTaperStart': '3243–3244: Sweep trace taper length in milliseconds at start if tapered (the taper starts at zero time and is effective for this length).',
            'SweepTaperEnd': '3245–3246: Sweep trace taper length in milliseconds at end (the ending taper starts at sweep length minus the taper length at end).',
            'Taper': '3247–3248: Taper type: 1 = linear, 2 = cosine squared, 3 = other',
            'CorrelatedTraces': '3249–3250: Correlated data traces: 1 = no, 2 = yes',
            'BinaryGainRecovery': '3251–3252: Binary gain recovered: 1 = yes, 2 = no',
            'AmplitudeRecovery': '3253–3254: Amplitude recovery method: 1 = none, 2 = spherical divergence, 3 = AGC, 4 = other',
            'MeasurementSystem': '3255–3256: Measurement system: 1 = Meters, 2 = Feet',
            'ImpulseSignalPolarity': '3257–3258: Impulse signal polarity',
            'VibratoryPolarity': '3259–3260: Vibratory polarity code',
            'ExtAuxTraces': '3261–3264: Extended number of data traces per ensemble. If nonzero, this overrides the number of data traces per ensemble in bytes 3213–3214.',
            'ExtSamples': '3265–3268: Extended number of auxiliary traces per ensemble. If nonzero, this overrides the number of auxiliary traces per ensemble in bytes 3215–3216.',
            'ExtSamplesOriginal': '3269–3272: Extended number of samples per data trace. If nonzero, this overrides the number of samples per data trace in bytes 3221–3222.',
            'ExtEnsembleFold': '3273–3280: Extended sample interval, IEEE double precision (64-bit). If nonzero, this overrides the sample interval in bytes 3217–3218 with the same units.',
            'SEGYRevision': '3501: Major SEG-Y Format Revision Number. This is an 8-bit unsigned value. Thus for SEG-Y Revision 2.0, as defined in this document, this will be recorded as 0216.',
            'SEGYRevisionMinor': '3502: Minor SEG-Y Format Revision Number. This is an 8-bit unsigned value with a radix point between the first and second bytes. Thus for SEG-Y Revision 2.0, as defined in this document, this will be recorded as 0016.',
            'TraceFlag': '3503–3504: Fixed length trace flag. A value of one indicates that all traces in this SEG-Y file are guaranteed to have the same sample interval, number of trace header blocks and trace samples.',
            'ExtendedHeaders': '3505–3506: Number of 3200-byte, Extended Textual File Header records following the Binary Header.',
            # Additional SEG-Y Rev 2.0 fields
            'MaxAdditionalTraceHeaders': '3507–3510: Maximum number of additional 240 byte trace headers. A value of zero indicates there are no additional 240 byte trace headers.',
            'TimeBasis': '3511–3512: Time basis code: 1 = Local, 2 = GMT (Greenwich Mean Time), 3 = Other, 4 = UTC (Coordinated Universal Time), 5 = GPS (Global Positioning System Time)',
            'AdditionalTraceHeaderBytes': '3513–3520: Number of traces in this file or stream. (64-bit unsigned integer value) If zero, all bytes in the file or stream are part of this SEG-Y dataset.',
            'ByteOffset': '3521–3528: Byte offset of first trace relative to start of file or stream if known, otherwise zero. (64-bit unsigned integer value)',
            'AdditionalTraceHeaderSamples': '3529–3532: Number of 3200-byte data trailer stanza records following the last trace (4 byte signed integer). A value of 0 indicates there are no trailer records.'
        }
        
        decoder_key = field_mappings.get(field_name)
        if decoder_key and decoder_key in decoder:
            # Get the current value for this field
            current_value = None
            if hasattr(self, 'current_bin_headers') and self.current_bin_headers:
                for key, value in self.current_bin_headers.items():
                    if str(key) == field_name:
                        current_value = value
                        break
            
            # Build description text
            description_text = f"<b>{field_name}</b><br><br>"
            
            # Add byte location information
            byte_info = byte_locations.get(field_name, 'Byte location not specified')
            description_text += f"<b>Byte Location:</b> {byte_info}<br><br>"
            
            description_text += f"<b>Current Value:</b> {current_value if current_value is not None else 'N/A'}<br><br>"
            description_text += "<b>Possible Values:</b><br>"
            
            for value, desc in decoder[decoder_key].items():
                description_text += f"• {value}: {desc}<br>"
            
            self.field_description_text.setHtml(description_text)
        else:
            # Even if no decoder, show byte location info
            byte_info = byte_locations.get(field_name, 'Byte location not specified')
            description_text = f"<b>{field_name}</b><br><br>"
            description_text += f"<b>Byte Location:</b> {byte_info}<br><br>"
            description_text += "No description available for this field."
            self.field_description_text.setHtml(description_text)
    
    def show_trace_field_description(self, field_name):
        """Show description for a trace header field"""
        # Trace header byte location mappings from SEG-Y Rev 2.0
        trace_byte_locations = {
            'TRACE_SEQUENCE_LINE': '1–4: Trace sequence number within line — Numbers continue to increase if the same line continues across multiple SEG-Y files.',
            'TRACE_SEQUENCE_FILE': '5–8: Trace sequence number within SEG-Y file — Each file starts with trace sequence one.',
            'FieldRecord': '9–12: Original field record number.',
            'TraceNumber': '13–16: Trace number within the original field record. If supplying multi-cable data with identical channel numbers on each cable, either supply the cable ID number in bytes 153–156 of SEG-Y Trace Header Extension 1 or enter (cable–1)*nchan_per_cable+channel_no here.',
            'EnergySourcePoint': '17–20: Energy source point number — Used when more than one record occurs at the same effective surface location. It is recommended that the new entry defined in Trace Header bytes 197–202 be used for shotpoint number.',
            'CDP': '21–24: Ensemble number (i.e. CDP, CMP, CRP, etc.)',
            'CDP_TRACE': '25–28: Trace number within the ensemble — Each ensemble starts with trace number one.',
            'TraceIdentificationCode': '29–30: Trace identification code: –1 = Other, 0 = Unknown, 1 = Time domain seismic data, 2 = Dead, 3 = Dummy, 4 = Time break, 5 = Uphole, 6 = Sweep, 7 = Timing, 8 = Waterbreak, 9 = Near-field gun signature, 10 = Far-field gun signature, 11 = Seismic pressure sensor, 12 = Multicomponent seismic sensor – Vertical component, 13 = Multicomponent seismic sensor – Cross-line component, 14 = Multicomponent seismic sensor – In-line component, 15 = Rotated multicomponent seismic sensor – Vertical component, 16 = Rotated multicomponent seismic sensor – Transverse component, 17 = Rotated multicomponent seismic sensor – Radial component, 18 = Vibrator reaction mass, 19 = Vibrator baseplate, 20 = Vibrator estimated ground force, 21 = Vibrator reference, 22 = Time-velocity pairs, 23 = Time-depth pairs, 24 = Depth-velocity pairs, 25 = Depth domain seismic data, 26 = Gravity potential, 27 = Electric field – Vertical component, 28 = Electric field – Cross-line component, 29 = Electric field – In-line component, 30 = Rotated electric field – Vertical component, 31 = Rotated electric field – Transverse component, 32 = Rotated electric field – Radial component, 33 = Magnetic field – Vertical component, 34 = Magnetic field – Cross-line component, 35 = Magnetic field – In-line component, 36 = Rotated magnetic field – Vertical component, 37 = Rotated magnetic field – Transverse component, 38 = Rotated magnetic field – Radial component, 39 = Rotational sensor – Pitch, 40 = Rotational sensor – Roll, 41 = Rotational sensor – Yaw, 42 … 255 = Reserved, 256 … N = optional use, (maximum N = 16,383) N+16,384 = Interpolated, i.e. not original, seismic trace.',
            'NSummedTraces': '31–32: Number of vertically summed traces yielding this trace. (1 is one trace, 2 is two summed traces, etc.)',
            'NStackedTraces': '33–34: Number of horizontally stacked traces yielding this trace. (1 is one trace, 2 is two stacked traces, etc.)',
            'DataUse': '35–36: Data use: 1 = Production, 2 = Test',
            'offset': '37–40: Distance from center of the source point to the center of the receiver group (negative if opposite to direction in which line is shot).',
            'ReceiverGroupElevation': '41–44: Elevation of receiver group. This is, of course, normally equal to or lower than the surface elevation at the group location. The scalar in Trace Header bytes 69–70 applies to these values. The units are feet or meters as specified in Binary File Header bytes 3255–3256. Elevations and depths and their signs (+ve or – ve) are tied to a vertical CRS defined through an Extended Textual Header (see Appendix D-1). Historical usage had been that all elevations above the vertical datum were positive and below were negative. Elevations should now be defined with respect to the CRS.',
            'SourceSurfaceElevation': '45–48: Surface elevation at source location. The scalar in Trace Header bytes 69–70 applies to these values. The units are feet or meters as specified in Binary File Header bytes 3255–3256. Elevations and depths and their signs (+ve or – ve) are tied to a vertical CRS defined through an Extended Textual Header (see Appendix D-1). Historical usage had been that all elevations above the vertical datum were positive and below were negative. Elevations should now be defined with respect to the CRS.',
            'SourceDepth': '49–52: Source depth below surface. The scalar in Trace Header bytes 69–70 applies to these values. The units are feet or meters as specified in Binary File Header bytes 3255–3256. Elevations and depths and their signs (+ve or – ve) are tied to a vertical CRS defined through an Extended Textual Header (see Appendix D-1). Historical usage had been that all elevations above the vertical datum were positive and below were negative. Elevations should now be defined with respect to the CRS.',
            'ReceiverDatumElevation': '53–56: Seismic Datum elevation at receiver group. (If different from the survey vertical datum, Seismic Datum should be defined through a vertical CRS in an extended textual stanza.) The scalar in Trace Header bytes 69–70 applies to these values. The units are feet or meters as specified in Binary File Header bytes 3255–3256. Elevations and depths and their signs (+ve or – ve) are tied to a vertical CRS defined through an Extended Textual Header (see Appendix D-1). Historical usage had been that all elevations above the vertical datum were positive and below were negative. Elevations should now be defined with respect to the CRS.',
            'SourceDatumElevation': '57–60: Seismic Datum elevation at source. (As above) The scalar in Trace Header bytes 69–70 applies to these values. The units are feet or meters as specified in Binary File Header bytes 3255–3256. Elevations and depths and their signs (+ve or – ve) are tied to a vertical CRS defined through an Extended Textual Header (see Appendix D-1). Historical usage had been that all elevations above the vertical datum were positive and below were negative. Elevations should now be defined with respect to the CRS.',
            'SourceWaterDepth': '61–64: Water column height at source location (at time of source event). The scalar in Trace Header bytes 69–70 applies to these values. The units are feet or meters as specified in Binary File Header bytes 3255–3256. Elevations and depths and their signs (+ve or – ve) are tied to a vertical CRS defined through an Extended Textual Header (see Appendix D-1). Historical usage had been that all elevations above the vertical datum were positive and below were negative. Elevations should now be defined with respect to the CRS.',
            'GroupWaterDepth': '65– 68: Water column height at receiver group location (at time of recording of first source event into that receiver). The scalar in Trace Header bytes 69–70 applies to these values. The units are feet or meters as specified in Binary File Header bytes 3255–3256. Elevations and depths and their signs (+ve or – ve) are tied to a vertical CRS defined through an Extended Textual Header (see Appendix D-1). Historical usage had been that all elevations above the vertical datum were positive and below were negative. Elevations should now be defined with respect to the CRS.',
            'ElevationScalar': '69–70: Scalar to be applied to all elevations and depths specified in Standard Trace Header bytes 41–68 to give the real value. Scalar = 1, ±10, ±100, ±1000, or ±10,000. If positive, scalar is used as a multiplier; if negative, scalar is used as a divisor. A value of zero is assumed to be a scalar value of 1.',
            'SourceGroupScalar': '71–72: Scalar to be applied to all coordinates specified in Standard Trace Header bytes 73–88 and to bytes Trace Header 181–188 to give the real value. Scalar = 1, ±10, ±100, ±1000, or ±10,000. If positive, scalar is used as a multiplier; if negative, scalar is used as divisor. A value of zero is assumed to be a scalar value of 1.',
            'SourceX': '73–76: Source coordinate – X. The coordinate reference system should be identified through an Extended Textual Header (see Appendix D-1). If the coordinate units are in seconds of arc, decimal degrees or DMS, the X values represent longitude and the Y values latitude. A positive value designates east of Greenwich Meridian or north of the equator and a negative value designates south or west.',
            'SourceY': '77–80: Source coordinate – Y. The coordinate reference system should be identified through an Extended Textual Header (see Appendix D-1). If the coordinate units are in seconds of arc, decimal degrees or DMS, the X values represent longitude and the Y values latitude. A positive value designates east of Greenwich Meridian or north of the equator and a negative value designates south or west.',
            'GroupX': '81–84: Group coordinate – X. The coordinate reference system should be identified through an Extended Textual Header (see Appendix D-1). If the coordinate units are in seconds of arc, decimal degrees or DMS, the X values represent longitude and the Y values latitude. A positive value designates east of Greenwich Meridian or north of the equator and a negative value designates south or west.',
            'GroupY': '85–88: Group coordinate – Y. The coordinate reference system should be identified through an Extended Textual Header (see Appendix D-1). If the coordinate units are in seconds of arc, decimal degrees or DMS, the X values represent longitude and the Y values latitude. A positive value designates east of Greenwich Meridian or north of the equator and a negative value designates south or west.',
            'CoordinateUnits': '89–90: Coordinate units: 1 = Length (meters or feet as specified in Binary File Header bytes 3255-3256 and in Extended Textual Header if Location Data are included in the file), 2 = Seconds of arc (deprecated), 3 = Decimal degrees (preferred degree representation), 4 = Degrees, minutes, seconds (DMS). Note: To encode ±DDDMMSS set bytes 73–88 = ±DDD*104 + MM*102 + SS with bytes 71–72 set to 1; To encode ±DDDMMSS.ss set bytes 73–88 = ±DDD*106 + MM*104 + SS*102 + ss with bytes 71–72 set to –100.',
            'WeatheringVelocity': '91–92: Weathering velocity. (ft/s or m/s as specified in Binary File Header bytes 3255– 3256)',
            'SubWeatheringVelocity': '93–94: Subweathering velocity. (ft/s or m/s as specified in Binary File Header bytes 3255–3256)',
            'SourceUpholeTime': '95–96: Uphole time at source in milliseconds. Time in milliseconds as scaled by the scalar specified in Standard Trace Header bytes 215-216.',
            'GroupUpholeTime': '97–98: Uphole time at group in milliseconds. Time in milliseconds as scaled by the scalar specified in Standard Trace Header bytes 215-216.',
            'SourceStaticCorrection': '99–100: Source static correction in milliseconds. Time in milliseconds as scaled by the scalar specified in Standard Trace Header bytes 215-216.',
            'GroupStaticCorrection': '101–102: Group static correction in milliseconds. Time in milliseconds as scaled by the scalar specified in Standard Trace Header bytes 215-216.',
            'TotalStaticApplied': '103–104: Total static applied in milliseconds. (Zero if no static has been applied,) Time in milliseconds as scaled by the scalar specified in Standard Trace Header bytes 215-216.',
            'LagTimeA': '105–106: Lag time A — Time in milliseconds between end of 240-byte trace identification header and time break. The value is positive if time break occurs after the end of header; negative if time break occurs before the end of header. Time break is defined as the initiation pulse that may be recorded on an auxiliary trace or as otherwise specified by the recording system.',
            'LagTimeB': '107–108: Lag Time B — Time in milliseconds between time break and the initiation time of the energy source. May be positive or negative.',
            'DelayRecordingTime': '109–110: Delay recording time — Time in milliseconds between initiation time of energy source and the time when recording of data samples begins. In SEG-Y rev 0 this entry was intended for deep-water work if data recording did not start at zero time. The entry can be negative to accommodate negative start times (i.e. data recorded before time zero, presumably as a result of static application to the data trace). If a non-zero value (negative or positive) is recorded in this entry, a comment to that effect should appear in the Textual File Header.',
            'MuteTimeStart': '111–112: Mute time — Start time in milliseconds.',
            'MuteTimeEND': '113–114: Mute time — End time in milliseconds.',
            'TRACE_SAMPLE_COUNT': '115–116: Number of samples in this trace. The number of bytes in a trace record must be consistent with the number of samples written in the Binary File Header and/or the SEG-defined Trace Header(s). This is important for all recording media; but it is particularly crucial for the correct processing of SEG-Y data in disk files (see Appendix A). If the fixed length trace flag in bytes 3503–3504 of the Binary File Header is set, the number of samples in every trace in the SEG-Y file is assumed to be the same as the value recorded in the Binary File Header and this field is ignored. If the fixed length trace flag is not set, the number of samples may vary from trace to trace.',
            'TRACE_SAMPLE_INTERVAL': '117–118: Sample interval for this trace. Microseconds (µs) for time data, Hertz (Hz) for frequency data, meters (m) or feet (ft) for depth data. If the fixed length trace flag in bytes 3503–3504 of the Binary File Header is set, the sample interval in every trace in the SEG-Y file is assumed to be the same as the value recorded in the Binary File Header and this field is ignored. If the fixed length trace flag is not set, the sample interval may vary from trace to trace.',
            'GainType': '119–120: Gain type of field instruments: 1 = fixed, 2 = binary, 3 = floating point, 4 … N = optional use',
            'InstrumentGainConstant': '121–122: Instrument gain constant (dB).',
            'InstrumentInitialGain': '123–124: Instrument early or initial gain (dB).',
            'Correlated': '125–126: Correlated: 1 = no, 2 = yes',
            'SweepFrequencyStart': '127–128: Sweep frequency at start (Hz).',
            'SweepFrequencyEnd': '129–130: Sweep frequency at end (Hz).',
            'SweepLength': '131–132: Sweep length in milliseconds.',
            'SweepType': '133–134: Sweep type: 1 = linear, 2 = parabolic, 3 = exponential, 4 = other',
            'SweepTraceTaperLengthStart': '135–136: Sweep trace taper length at start in milliseconds.',
            'SweepTraceTaperLengthEnd': '137–138: Sweep trace taper length at end in milliseconds.',
            'TaperType': '139–140: Taper type: 1 = linear, 2 = cos2, 3 = other',
            'AliasFilterFrequency': '141–142: Alias filter frequency (Hz), if used.',
            'AliasFilterSlope': '143–144: Alias filter slope (dB/octave).',
            'NotchFilterFrequency': '145–146: Notch filter frequency (Hz), if used.',
            'NotchFilterSlope': '147–148: Notch filter slope (dB/octave).',
            'LowCutFrequency': '149–150: Low-cut frequency (Hz), if used.',
            'HighCutFrequency': '151–152: High-cut frequency (Hz), if used.',
            'LowCutSlope': '153–154: Low-cut slope (dB/octave)',
            'HighCutSlope': '155–156: High-cut slope (dB/octave)',
            'YearDataRecorded': '157–158: Year data recorded — The 1975 standard was unclear as to whether this should be recorded as a 2-digit or a 4-digit year and both have been used. For SEG-Y revisions beyond rev 0, the year should be recorded as the complete 4-digit Gregorian calendar year, e.g., the year 2001 should be recorded as 2001 (07D116).',
            'DayOfYear': '159–160: Day of year (Range 1–366 for GMT, UTC, and GPS time basis).',
            'HourOfDay': '161–162: Hour of day (24 hour clock).',
            'MinuteOfHour': '163–164: Minute of hour.',
            'SecondOfMinute': '165–166: Second of minute.',
            'TimeBaseCode': '167–168: Time basis code. If nonzero, overrides Binary File Header bytes 3511–3512. 1 = Local, 2 = GMT (Greenwich Mean Time), 3 = Other, should be explained in a user defined stanza in the Extended Textual File Header, 4 = UTC (Coordinated Universal Time), 5 = GPS (Global Positioning System Time)',
            'TraceWeightingFactor': '169–170: Trace weighting factor — Defined as 2–N units (volts unless bytes 203–204 specify a different unit) for the least significant bit. (N = 0, 1, …, 32767)',
            'GeophoneGroupNumberRoll1': '171–172: Geophone group number of roll switch position one.',
            'GeophoneGroupNumberFirstTraceOrigField': '173–174: Geophone group number of trace number one within original field record.',
            'GeophoneGroupNumberLastTraceOrigField': '175–176: Geophone group number of last trace within original field record.',
            'GapSize': '177–178: Gap size (total number of groups dropped).',
            'OverTravel': '179–180: Over travel associated with taper at beginning or end of line: 1 = down (or behind), 2 = up (or ahead)',
            'CDP_X': '181–184: X coordinate of ensemble (CDP) position of this trace (scalar in Standard Trace Header bytes 71–72 applies). The coordinate reference system should be identified through an Extended Textual Header (see Appendices D-1 or D-3).',
            'CDP_Y': '185–188: Y coordinate of ensemble (CDP) position of this trace (scalar in Standard Trace Header bytes 71–72 applies). The coordinate reference system should be identified through an Extended Textual Header (see Appendices D-1 or D-3).',
            'INLINE_3D': '189–192: For 3-D poststack data, this field should be used for the in-line number. If one in-line per SEG-Y file is being recorded, this value should be the same for all traces in the file and the same value will be recorded in bytes 3205–3208 of the Binary File Header.',
            'CROSSLINE_3D': '193–196: For 3-D poststack data, this field should be used for the cross-line number. This will typically be the same value as the ensemble (CDP) number in Standard Trace Header bytes 21–24, but this does not have to be the case.',
            'ShotPoint': '197–200: Shotpoint number — This is probably only applicable to 2-D poststack data. Note that it is assumed that the shotpoint number refers to the source location nearest to the ensemble (CDP) location for a particular trace. If this is not the case, there should be a comment in the Textual File Header explaining what the shotpoint number actually refers to.',
            'ShotPointScalar': '201–202: Scalar to be applied to the shotpoint number in Standard Trace Header bytes 197–200 to give the real value. If positive, scalar is used as a multiplier; if negative as a divisor; if zero the shotpoint number is not scaled (i.e. it is an integer. A typical value will be –10, allowing shotpoint numbers with one decimal digit to the right of the decimal point).',
            'TraceValueMeasurementUnit': '203–204: Trace value measurement unit: –1 = Other (should be described in Data Sample Measurement Units Stanza), 0 = Unknown, 1 = Pascal (Pa), 2 = Volts (v), 3 = Millivolts (mV), 4 = Amperes (A), 5 = Meters (m), 6 = Meters per second (m/s), 7 = Meters per second squared (m/s2), 8 = Newton (N), 9 = Watt (W), 10-255 = reserved for future use, 256 … N = optional use. (maximum N = 32,767)'
        }
        
        # Get the current value for this field
        current_value = None
        if hasattr(self, 'current_trace_headers') and self.current_trace_headers:
            for key, value in self.current_trace_headers.items():
                if str(key) == field_name:
                    current_value = value
                    break
        
        # Build description text
        description_text = f"<b>{field_name}</b><br><br>"
        
        # Add byte location information
        byte_info = trace_byte_locations.get(field_name, 'Byte location not specified')
        description_text += f"<b>Byte Location:</b> {byte_info}<br><br>"
        
        description_text += f"<b>Current Value:</b> {current_value if current_value is not None else 'N/A'}<br><br>"
        description_text += "This is a trace header field from the SEG-Y Rev 2.0 specification."
        
        self.field_description_text.setHtml(description_text)
    
    def get_binary_header_decoder(self):
        """Get decoder for binary header field values with descriptions based on SEG-Y Rev 2.0"""
        decoder = {
            # Data sample format code (bytes 3225-3226)
            'DataSampleFormat': {
                1: '4-byte IBM floating-point',
                2: '4-byte, two\'s complement integer',
                3: '2-byte, two\'s complement integer',
                4: '4-byte fixed-point with gain (obsolete)',
                5: '4-byte IEEE floating-point',
                6: '8-byte IEEE floating-point',
                7: '3-byte two\'s complement integer',
                8: '1-byte, two\'s complement integer',
                9: '8-byte, two\'s complement integer',
                10: '4-byte, unsigned integer',
                11: '2-byte, unsigned integer',
                12: '8-byte, unsigned integer',
                15: '3-byte, unsigned integer',
                16: '1-byte, unsigned integer'
            },
            
            # Trace sorting code (bytes 3229-3230)
            'TraceSortingCode': {
                -1: 'Other (should be explained in Extended Textual File Header)',
                0: 'Unknown',
                1: 'As recorded (no sorting)',
                2: 'CDP ensemble',
                3: 'Single fold continuous profile',
                4: 'Horizontally stacked',
                5: 'Common source point',
                6: 'Common receiver point',
                7: 'Common offset point',
                8: 'Common mid-point',
                9: 'Common conversion point'
            },
            
            # Sweep type code (bytes 3239-3240)
            'SweepTypeCode': {
                1: 'Linear',
                2: 'Parabolic',
                3: 'Exponential',
                4: 'Other'
            },
            
            # Taper type (bytes 3247-3248)
            'TaperType': {
                1: 'Linear',
                2: 'Cosine squared',
                3: 'Other'
            },
            
            # Correlated data traces (bytes 3249-3250)
            'CorrelatedDataTraces': {
                1: 'No',
                2: 'Yes'
            },
            
            # Binary gain recovered (bytes 3251-3252)
            'BinaryGainRecovered': {
                1: 'Yes',
                2: 'No'
            },
            
            # Amplitude recovery method (bytes 3253-3254)
            'AmplitudeRecoveryMethod': {
                1: 'None',
                2: 'Spherical divergence',
                3: 'AGC',
                4: 'Other'
            },
            
            # Measurement system (bytes 3255-3256)
            'MeasurementSystem': {
                1: 'Meters',
                2: 'Feet'
            },
            
            # Impulse signal polarity (bytes 3257-3258)
            'ImpulseSignalPolarity': {
                1: 'Increase in pressure or upward geophone case movement gives negative number on trace',
                2: 'Increase in pressure or upward geophone case movement gives positive number on trace'
            },
            
            # Vibratory polarity code (bytes 3259-3260)
            'VibratoryPolarityCode': {
                1: 'Seismic signal lags pilot signal by 337.5° to 22.5°',
                2: 'Seismic signal lags pilot signal by 22.5° to 67.5°',
                3: 'Seismic signal lags pilot signal by 67.5° to 112.5°',
                4: 'Seismic signal lags pilot signal by 112.5° to 157.5°',
                5: 'Seismic signal lags pilot signal by 157.5° to 202.5°',
                6: 'Seismic signal lags pilot signal by 202.5° to 247.5°',
                7: 'Seismic signal lags pilot signal by 247.5° to 292.5°',
                8: 'Seismic signal lags pilot signal by 292.5° to 337.5°'
            },
            
            # Time basis code (bytes 3511-3512)
            'TimeBasisCode': {
                1: 'Local',
                2: 'GMT (Greenwich Mean Time)',
                3: 'Other (should be explained in Extended Textual File Header)',
                4: 'UTC (Coordinated Universal Time)',
                5: 'GPS (Global Positioning System Time)'
            },
            
            # Fixed length trace flag (bytes 3503-3504)
            'FixedLengthTraceFlag': {
                0: 'Variable length traces (traditional SEG-Y)',
                1: 'Fixed length traces (all traces have same sample interval and number of samples)'
            },
            
            # Additional binary header fields from SEG-Y Rev 2.0 specification
            
            # Job identification number (bytes 3201-3204)
            'JobIdentificationNumber': {
                # This is typically a user-defined number, no standard values
            },
            
            # Line number (bytes 3205-3208)
            'LineNumber': {
                # This is typically a user-defined number, no standard values
            },
            
            # Reel number (bytes 3209-3212)
            'ReelNumber': {
                # This is typically a user-defined number, no standard values
            },
            
            # Number of data traces per record (bytes 3213-3214)
            'NumberOfDataTracesPerRecord': {
                # This is typically a user-defined number, no standard values
            },
            
            # Number of auxiliary traces per record (bytes 3215-3216)
            'NumberOfAuxiliaryTracesPerRecord': {
                # This is typically a user-defined number, no standard values
            },
            
            # Sample interval in microseconds (bytes 3217-3218)
            'SampleIntervalInMicroseconds': {
                # This is typically a user-defined number, no standard values
            },
            
            # Sample interval in microseconds of original field recording (bytes 3219-3220)
            'SampleIntervalInMicrosecondsOfOriginalFieldRecording': {
                # This is typically a user-defined number, no standard values
            },
            
            # Number of samples per data trace (bytes 3221-3222)
            'NumberOfSamplesPerDataTrace': {
                # This is typically a user-defined number, no standard values
            },
            
            # Number of samples per data trace for original field recording (bytes 3223-3224)
            'NumberOfSamplesPerDataTraceForOriginalFieldRecording': {
                # This is typically a user-defined number, no standard values
            },
            
            # Ensemble fold (bytes 3227-3228)
            'EnsembleFold': {
                # This is typically a user-defined number, no standard values
            },
            
            # Vertical sum code (bytes 3231-3232)
            'VerticalSumCode': {
                1: 'No sum',
                2: 'Two sum',
                3: 'Three sum',
                4: 'Four sum',
                5: 'Five sum',
                6: 'Six sum',
                7: 'Seven sum',
                8: 'Eight sum',
                9: 'Nine sum',
                10: 'Ten sum',
                11: 'Eleven sum',
                12: 'Twelve sum',
                13: 'Thirteen sum',
                14: 'Fourteen sum',
                15: 'Fifteen sum',
                16: 'Sixteen sum'
            },
            
            # Sweep frequency at start (bytes 3233-3234)
            'SweepFrequencyAtStart': {
                # This is typically a user-defined number, no standard values
            },
            
            # Sweep frequency at end (bytes 3235-3236)
            'SweepFrequencyAtEnd': {
                # This is typically a user-defined number, no standard values
            },
            
            # Sweep length in milliseconds (bytes 3237-3238)
            'SweepLengthInMilliseconds': {
                # This is typically a user-defined number, no standard values
            },
            
            # Sweep channel number (bytes 3241-3242)
            'SweepChannelNumber': {
                # This is typically a user-defined number, no standard values
            },
            
            # Sweep trace taper length at start in milliseconds (bytes 3243-3244)
            'SweepTraceTaperLengthAtStartInMilliseconds': {
                # This is typically a user-defined number, no standard values
            },
            
            # Sweep trace taper length at end in milliseconds (bytes 3245-3246)
            'SweepTraceTaperLengthAtEndInMilliseconds': {
                # This is typically a user-defined number, no standard values
            },
            
            # Extended number of auxiliary traces per record (bytes 3255-3256)
            'ExtendedNumberOfAuxiliaryTracesPerRecord': {
                # This is typically a user-defined number, no standard values
            },
            
            # Extended number of samples per data trace (bytes 3257-3258)
            'ExtendedNumberOfSamplesPerDataTrace': {
                # This is typically a user-defined number, no standard values
            },
            
            # Extended number of samples per data trace for original field recording (bytes 3259-3260)
            'ExtendedNumberOfSamplesPerDataTraceForOriginalFieldRecording': {
                # This is typically a user-defined number, no standard values
            },
            
            # Extended ensemble fold (bytes 3261-3262)
            'ExtendedEnsembleFold': {
                # This is typically a user-defined number, no standard values
            },
            
            # SEG-Y format revision number (bytes 3501-3502)
            'SEGYFormatRevisionNumber': {
                0: 'SEG-Y Rev 0',
                1: 'SEG-Y Rev 1',
                2: 'SEG-Y Rev 2'
            },
            
            # SEG-Y format revision number minor (bytes 3503-3504)
            'SEGYFormatRevisionNumberMinor': {
                # This is typically a user-defined number, no standard values
            },
            
            # Number of extended textual file header records (bytes 3505-3506)
            'NumberOfExtendedTextualFileHeaderRecords': {
                # This is typically a user-defined number, no standard values
            }
        }
        return decoder
    
    def decode_binary_header_value(self, field_name, value):
        """Decode a binary header field value to its description"""
        decoder = self.get_binary_header_decoder()
        
        # Convert field_name to string if it's a BinField object
        field_name_str = str(field_name)
        
        # Handle segyio's actual field names (based on the test output)
        field_mappings = {
            'DataSampleFormat': ['Format'],
            'TraceSortingCode': ['SortingCode'],
            'SweepTypeCode': ['Sweep'],
            'TaperType': ['Taper'],
            'CorrelatedDataTraces': ['CorrelatedTraces'],
            'BinaryGainRecovered': ['BinaryGainRecovery'],
            'AmplitudeRecoveryMethod': ['AmplitudeRecovery'],
            'MeasurementSystem': ['MeasurementSystem'],
            'ImpulseSignalPolarity': ['ImpulseSignalPolarity'],
            'VibratoryPolarityCode': ['VibratoryPolarity'],
            'FixedLengthTraceFlag': ['TraceFlag'],
            'JobIdentificationNumber': ['JobID'],
            'LineNumber': ['LineNumber'],
            'ReelNumber': ['ReelNumber'],
            'NumberOfDataTracesPerRecord': ['Traces'],
            'NumberOfAuxiliaryTracesPerRecord': ['AuxTraces'],
            'SampleIntervalInMicroseconds': ['Interval'],
            'SampleIntervalInMicrosecondsOfOriginalFieldRecording': ['IntervalOriginal'],
            'NumberOfSamplesPerDataTrace': ['Samples'],
            'NumberOfSamplesPerDataTraceForOriginalFieldRecording': ['SamplesOriginal'],
            'EnsembleFold': ['EnsembleFold'],
            'VerticalSumCode': ['VerticalSum'],
            'SweepFrequencyAtStart': ['SweepFrequencyStart'],
            'SweepFrequencyAtEnd': ['SweepFrequencyEnd'],
            'SweepLengthInMilliseconds': ['SweepLength'],
            'SweepChannelNumber': ['SweepChannel'],
            'SweepTraceTaperLengthAtStartInMilliseconds': ['SweepTaperStart'],
            'SweepTraceTaperLengthAtEndInMilliseconds': ['SweepTaperEnd'],
            'ExtendedNumberOfAuxiliaryTracesPerRecord': ['ExtAuxTraces'],
            'ExtendedNumberOfSamplesPerDataTrace': ['ExtSamples'],
            'ExtendedNumberOfSamplesPerDataTraceForOriginalFieldRecording': ['ExtSamplesOriginal'],
            'ExtendedEnsembleFold': ['ExtEnsembleFold'],
            'SEGYFormatRevisionNumber': ['SEGYRevision'],
            'SEGYFormatRevisionNumberMinor': ['SEGYRevisionMinor'],
            'NumberOfExtendedTextualFileHeaderRecords': ['ExtendedHeaders']
        }
        
        # Find the correct decoder key
        decoder_key = None
        for key, variations in field_mappings.items():
            if field_name_str in variations:
                decoder_key = key
                break
        
        if decoder_key and decoder_key in decoder:
            if value in decoder[decoder_key]:
                result = decoder[decoder_key][value]
                return result
            else:
                return None  # Value not found in decoder, don't show "Unknown value"
        else:
            return None  # No decoder available for this field

    def get_byte_location_mapping(self):
        """Get mapping of segyio field names to byte locations based on standard SEGY format"""
        # This mapping is based on the actual segyio field names and their standard SEGY byte locations
        # Each entry maps segyio field name to byte range in the 240-byte trace header
        byte_mapping = {
            # Bytes 1-4: Trace sequence number within line
            'TRACE_SEQUENCE_LINE': '1-4',
            'TRACE_SEQUENCE_NUMBER_LINE': '1-4',
            
            # Bytes 5-8: Trace sequence number within reel/file
            'TRACE_SEQUENCE_FILE': '5-8',
            'TRACE_SEQUENCE_NUMBER_REEL': '5-8',
            'TRACE_SEQUENCE_NUMBER_FILE': '5-8',
            
            # Bytes 9-12: Original field record number
            'FieldRecord': '9-12',
            'FIELD_RECORD': '9-12',
            'ORIGINAL_FIELD_RECORD': '9-12',
            
            # Bytes 13-16: Trace number within original field record
            'TraceNumber': '13-16',
            'TRACE_NUMBER': '13-16',
            'TRACE_NUMBER_WITHIN_ORIGINAL_FIELD_RECORD': '13-16',
            
            # Bytes 17-20: Energy source point number
            'EnergySourcePoint': '17-20',
            'ENERGY_SOURCE_POINT': '17-20',
            'ENERGY_SOURCE_POINT_NUMBER': '17-20',
            
            # Bytes 21-24: CDP ensemble number
            'CDPEnsemble': '21-24',
            'CDP_ENSEMBLE': '21-24',
            'CDP_ENSEMBLE_NUMBER': '21-24',
            'CDP': '21-24',
            
            # Bytes 25-26: Trace number within CDP ensemble
            'TraceInEnsemble': '25-26',
            'TRACE_IN_ENSEMBLE': '25-26',
            'TRACE_NUMBER_WITHIN_CDP_ENSEMBLE': '25-26',
            'CDP_TRACE': '25-26',
            
            # Bytes 27-28: Trace identification code
            'TraceIdentificationCode': '27-28',
            'TRACE_IDENTIFICATION_CODE': '27-28',
            'TRACE_ID_CODE': '27-28',
            
            # Bytes 29-30: Number of vertically summed traces
            'NumberOfVerticallySummedTraces': '29-30',
            'NUMBER_OF_VERTICALLY_SUMMED_TRACES': '29-30',
            'VERTICALLY_SUMMED_TRACES': '29-30',
            'NSummedTraces': '29-30',
            
            # Bytes 31-32: Number of horizontally stacked traces
            'NumberOfHorizontallyStackedTraces': '31-32',
            'NUMBER_OF_HORIZONTALLY_STACKED_TRACES': '31-32',
            'HORIZONTALLY_STACKED_TRACES': '31-32',
            'NStackedTraces': '31-32',
            
            # Bytes 33-34: Data use
            'DataUse': '33-34',
            'DATA_USE': '33-34',
            'DATA_USE_CODE': '33-34',
            
            # Bytes 35-40: Distance from center of source point to center of receiver group
            'DistanceFromCenterOfSourcePoint': '35-40',
            'DISTANCE_FROM_CENTER_OF_SOURCE_POINT': '35-40',
            'DISTANCE_CENTER_SOURCE_TO_RECEIVER': '35-40',
            'offset': '35-40',
            
            # Bytes 41-44: Receiver group elevation
            'ReceiverGroupElevation': '41-44',
            'RECEIVER_GROUP_ELEVATION': '41-44',
            'GROUP_ELEVATION': '41-44',
            
            # Bytes 45-48: Surface elevation at source
            'SurfaceElevationAtSource': '45-48',
            'SURFACE_ELEVATION_AT_SOURCE': '45-48',
            'SOURCE_SURFACE_ELEVATION': '45-48',
            'SourceSurfaceElevation': '45-48',
            
            # Bytes 49-52: Source depth below surface
            'SourceDepthBelowSurface': '49-52',
            'SOURCE_DEPTH_BELOW_SURFACE': '49-52',
            'SOURCE_DEPTH': '49-52',
            'SourceDepth': '49-52',
            
            # Bytes 53-56: Datum elevation at receiver group
            'DatumElevationAtReceiverGroup': '53-56',
            'DATUM_ELEVATION_AT_RECEIVER_GROUP': '53-56',
            'RECEIVER_DATUM_ELEVATION': '53-56',
            'ReceiverDatumElevation': '53-56',
            
            # Bytes 57-60: Datum elevation at source
            'DatumElevationAtSource': '57-60',
            'DATUM_ELEVATION_AT_SOURCE': '57-60',
            'SOURCE_DATUM_ELEVATION': '57-60',
            'SourceDatumElevation': '57-60',
            
            # Bytes 61-64: Water depth at source
            'WaterDepthAtSource': '61-64',
            'WATER_DEPTH_AT_SOURCE': '61-64',
            'SOURCE_WATER_DEPTH': '61-64',
            'SourceWaterDepth': '61-64',
            
            # Bytes 65-68: Water depth at group
            'WaterDepthAtGroup': '65-68',
            'WATER_DEPTH_AT_GROUP': '65-68',
            'GROUP_WATER_DEPTH': '65-68',
            'GroupWaterDepth': '65-68',
            
            # Bytes 69-70: Scalar for elevations and depths
            'ScalarForElevationsAndDepths': '69-70',
            'SCALAR_FOR_ELEVATIONS_AND_DEPTHS': '69-70',
            'ELEVATION_DEPTH_SCALAR': '69-70',
            'ElevationScalar': '69-70',
            
            # Bytes 71-72: Scalar for coordinates
            'ScalarForCoordinates': '71-72',
            'SCALAR_FOR_COORDINATES': '71-72',
            'COORDINATE_SCALAR': '71-72',
            
            # Bytes 73-76: Source coordinate X
            'SourceCoordinateX': '73-76',
            'SOURCE_COORDINATE_X': '73-76',
            'SOURCE_X': '73-76',
            'SourceX': '73-76',
            
            # Bytes 77-80: Source coordinate Y
            'SourceCoordinateY': '77-80',
            'SOURCE_COORDINATE_Y': '77-80',
            'SOURCE_Y': '77-80',
            'SourceY': '77-80',
            
            # Bytes 81-84: Group coordinate X
            'GroupCoordinateX': '81-84',
            'GROUP_COORDINATE_X': '81-84',
            'GROUP_X': '81-84',
            'GroupX': '81-84',
            
            # Bytes 85-88: Group coordinate Y
            'GroupCoordinateY': '85-88',
            'GROUP_COORDINATE_Y': '85-88',
            'GROUP_Y': '85-88',
            'GroupY': '85-88',
            
            # Bytes 89-90: Coordinate units
            'CoordinateUnits': '89-90',
            'COORDINATE_UNITS': '89-90',
            'COORD_UNITS': '89-90',
            
            # Bytes 91-92: Weathering velocity
            'WeatheringVelocity': '91-92',
            'WEATHERING_VELOCITY': '91-92',
            'WEATHERING_VEL': '91-92',
            
            # Bytes 93-94: Sub-weathering velocity
            'SubWeatheringVelocity': '93-94',
            'SUB_WEATHERING_VELOCITY': '93-94',
            'SUB_WEATHERING_VEL': '93-94',
            
            # Bytes 95-96: Uphole time at source
            'SourceUpholeTime': '95-96',
            'SOURCE_UPHOLE_TIME': '95-96',
            'SOURCE_UPHOLE': '95-96',
            
            # Bytes 97-98: Uphole time at group
            'GroupUpholeTime': '97-98',
            'GROUP_UPHOLE_TIME': '97-98',
            'GROUP_UPHOLE': '97-98',
            
            # Bytes 99-100: Source static correction
            'SourceStaticCorrection': '99-100',
            'SOURCE_STATIC_CORRECTION': '99-100',
            'SOURCE_STATIC': '99-100',
            
            # Bytes 101-102: Group static correction
            'GroupStaticCorrection': '101-102',
            'GROUP_STATIC_CORRECTION': '101-102',
            'GROUP_STATIC': '101-102',
            
            # Bytes 103-104: Total static applied
            'TotalStaticApplied': '103-104',
            'TOTAL_STATIC_APPLIED': '103-104',
            'TOTAL_STATIC': '103-104',
            
            # Bytes 105-106: Lag time A
            'LagTimeA': '105-106',
            'LAG_TIME_A': '105-106',
            'LAG_A': '105-106',
            
            # Bytes 107-108: Lag time B
            'LagTimeB': '107-108',
            'LAG_TIME_B': '107-108',
            'LAG_B': '107-108',
            
            # Bytes 109-110: Delay recording time
            'DelayRecordingTime': '109-110',
            'DELAY_RECORDING_TIME': '109-110',
            'DELAY_TIME': '109-110',
            
            # Bytes 111-112: Mute time start
            'MuteTimeStart': '111-112',
            'MUTE_TIME_START': '111-112',
            'MUTE_START': '111-112',
            
            # Bytes 113-114: Mute time end
            'MuteTimeEnd': '113-114',
            'MUTE_TIME_END': '113-114',
            'MUTE_END': '113-114',
            'MuteTimeEND': '113-114',
            
            # Bytes 115-116: Number of samples in this trace
            'NumberOfSamples': '115-116',
            'NUMBER_OF_SAMPLES': '115-116',
            'SAMPLES': '115-116',
            'TRACE_SAMPLE_COUNT': '115-116',
            
            # Bytes 117-118: Sample interval in microseconds
            'SampleInterval': '117-118',
            'SAMPLE_INTERVAL': '117-118',
            'SAMPLE_RATE': '117-118',
            'TRACE_SAMPLE_INTERVAL': '117-118',
            
            # Bytes 119-120: Gain type of field instruments
            'GainType': '119-120',
            'GAIN_TYPE': '119-120',
            'INSTRUMENT_GAIN_TYPE': '119-120',
            
            # Bytes 121-122: Instrument gain constant
            'InstrumentGainConstant': '121-122',
            'INSTRUMENT_GAIN_CONSTANT': '121-122',
            'GAIN_CONSTANT': '121-122',
            
            # Bytes 123-124: Instrument early or initial gain
            'InstrumentInitialGain': '123-124',
            'INSTRUMENT_INITIAL_GAIN': '123-124',
            'INITIAL_GAIN': '123-124',
            
            # Bytes 125-126: Correlated
            'Correlated': '125-126',
            'CORRELATED': '125-126',
            'CORRELATION_FLAG': '125-126',
            
            # Bytes 127-128: Sweep frequency at start
            'SweepFrequencyStart': '127-128',
            'SWEEP_FREQUENCY_START': '127-128',
            'SWEEP_START_FREQ': '127-128',
            
            # Bytes 129-130: Sweep frequency at end
            'SweepFrequencyEnd': '129-130',
            'SWEEP_FREQUENCY_END': '129-130',
            'SWEEP_END_FREQ': '129-130',
            
            # Bytes 131-132: Sweep length in milliseconds
            'SweepLength': '131-132',
            'SWEEP_LENGTH': '131-132',
            'SWEEP_DURATION': '131-132',
            
            # Bytes 133-134: Sweep type
            'SweepType': '133-134',
            'SWEEP_TYPE': '133-134',
            'SWEEP_TYPE_CODE': '133-134',
            
            # Bytes 135-136: Trace number of sweep channel
            'TraceNumberOfSweepChannel': '135-136',
            'TRACE_NUMBER_OF_SWEEP_CHANNEL': '135-136',
            'SWEEP_CHANNEL_TRACE': '135-136',
            
            # Bytes 137-138: Sweep trace taper length at start
            'SweepTraceTaperLengthStart': '137-138',
            'SWEEP_TRACE_TAPER_LENGTH_START': '137-138',
            'SWEEP_TAPER_START': '137-138',
            
            # Bytes 139-140: Sweep trace taper length at end
            'SweepTraceTaperLengthEnd': '139-140',
            'SWEEP_TRACE_TAPER_LENGTH_END': '139-140',
            'SWEEP_TAPER_END': '139-140',
            
            # Bytes 141-142: Taper type
            'TaperType': '141-142',
            'TAPER_TYPE': '141-142',
            'TAPER_TYPE_CODE': '141-142',
            
            # Bytes 143-144: Alias filter frequency
            'AliasFilterFrequency': '143-144',
            'ALIAS_FILTER_FREQUENCY': '143-144',
            'ALIAS_FREQ': '143-144',
            
            # Bytes 145-146: Alias filter slope
            'AliasFilterSlope': '145-146',
            'ALIAS_FILTER_SLOPE': '145-146',
            'ALIAS_SLOPE': '145-146',
            
            # Bytes 147-148: Notch filter frequency
            'NotchFilterFrequency': '147-148',
            'NOTCH_FILTER_FREQUENCY': '147-148',
            'NOTCH_FREQ': '147-148',
            
            # Bytes 149-150: Notch filter slope
            'NotchFilterSlope': '149-150',
            'NOTCH_FILTER_SLOPE': '149-150',
            'NOTCH_SLOPE': '149-150',
            
            # Bytes 151-152: Low-cut frequency
            'LowCutFrequency': '151-152',
            'LOW_CUT_FREQUENCY': '151-152',
            'LOW_CUT_FREQ': '151-152',
            
            # Bytes 153-154: High-cut frequency
            'HighCutFrequency': '153-154',
            'HIGH_CUT_FREQUENCY': '153-154',
            'HIGH_CUT_FREQ': '153-154',
            
            # Bytes 155-156: Low-cut slope
            'LowCutSlope': '155-156',
            'LOW_CUT_SLOPE': '155-156',
            'LOW_CUT_SLOPE_DB': '155-156',
            
            # Bytes 157-158: High-cut slope
            'HighCutSlope': '157-158',
            'HIGH_CUT_SLOPE': '157-158',
            'HIGH_CUT_SLOPE_DB': '157-158',
            
            # Bytes 159-160: Year data recorded
            'YearDataRecorded': '159-160',
            'YEAR_DATA_RECORDED': '159-160',
            'RECORDING_YEAR': '159-160',
            
            # Bytes 161-162: Day of year
            'DayOfYear': '161-162',
            'DAY_OF_YEAR': '161-162',
            'JULIAN_DAY': '161-162',
            
            # Bytes 163-164: Hour of day
            'HourOfDay': '163-164',
            'HOUR_OF_DAY': '163-164',
            'RECORDING_HOUR': '163-164',
            
            # Bytes 165-166: Minute of hour
            'MinuteOfHour': '165-166',
            'MINUTE_OF_HOUR': '165-166',
            'RECORDING_MINUTE': '165-166',
            
            # Bytes 167-168: Second of minute
            'SecondOfMinute': '167-168',
            'SECOND_OF_MINUTE': '167-168',
            'RECORDING_SECOND': '167-168',
            
            # Bytes 169-170: Time basis code
            'TimeBasisCode': '169-170',
            'TIME_BASIS_CODE': '169-170',
            'TIME_BASIS': '169-170',
            'TimeBaseCode': '169-170',
            
            # Bytes 171-172: Trace weighting factor
            'TraceWeightingFactor': '171-172',
            'TRACE_WEIGHTING_FACTOR': '171-172',
            'WEIGHTING_FACTOR': '171-172',
            
            # Bytes 173-174: Geophone group number of roll switch position one
            'GeophoneGroupNumberRoll1': '173-174',
            'GEOPHONE_GROUP_NUMBER_ROLL1': '173-174',
            'GEOPHONE_ROLL1': '173-174',
            
            # Bytes 175-176: Geophone group number of trace one within original field record
            'GeophoneGroupNumberFirstTraceOrigField': '175-176',
            'GEOPHONE_GROUP_NUMBER_FIRST_TRACE_ORIG_FIELD': '175-176',
            'GEOPHONE_FIRST_TRACE': '175-176',
            
            # Bytes 177-178: Geophone group number of last trace within original field record
            'GeophoneGroupNumberLastTraceOrigField': '177-178',
            'GEOPHONE_GROUP_NUMBER_LAST_TRACE_ORIG_FIELD': '177-178',
            'GEOPHONE_LAST_TRACE': '177-178',
            
            # Bytes 179-180: Gap size
            'GapSize': '179-180',
            'GAP_SIZE': '179-180',
            'GAP': '179-180',
            
            # Bytes 181-182: Over travel associated with taper
            'OverTravel': '181-182',
            'OVER_TRAVEL': '181-182',
            'OVER_TRAVEL_TAPER': '181-182',
            
            # Bytes 183-184: CDP X coordinate
            'CDPX': '183-184',
            'CDP_X': '183-184',
            'CDP_X_COORDINATE': '183-184',
            
            # Bytes 185-188: CDP Y coordinate
            'CDPY': '185-188',
            'CDP_Y': '185-188',
            'CDP_Y_COORDINATE': '185-188',
            
            # Bytes 189-192: Inline number
            'InlineNumber': '189-192',
            'INLINE_NUMBER': '189-192',
            'INLINE': '189-192',
            'INLINE_3D': '189-192',
            
            # Bytes 193-196: Crossline number
            'CrosslineNumber': '193-196',
            'CROSSLINE_NUMBER': '193-196',
            'CROSSLINE': '193-196',
            'CROSSLINE_3D': '193-196',
            
            # Bytes 197-200: Shotpoint number
            'ShotpointNumber': '197-200',
            'SHOTPOINT_NUMBER': '197-200',
            'SHOTPOINT': '197-200',
            'ShotPoint': '197-200',
            
            # Bytes 201-202: Shotpoint scalar
            'ShotpointScalar': '201-202',
            'SHOTPOINT_SCALAR': '201-202',
            'SHOTPOINT_SCALE': '201-202',
            'ShotPointScalar': '201-202',
            
            # Bytes 203-204: Trace value measurement unit
            'TraceValueMeasurementUnit': '203-204',
            'TRACE_VALUE_MEASUREMENT_UNIT': '203-204',
            'TRACE_UNIT': '203-204',
            
            # Bytes 205-208: Transduction constant mantissa
            'TransductionConstantMantissa': '205-208',
            'TRANSDUCTION_CONSTANT_MANTISSA': '205-208',
            'TRANSDUCTION_MANTISSA': '205-208',
            
            # Bytes 209-210: Transduction constant exponent
            'TransductionConstantExponent': '209-210',
            'TRANSDUCTION_CONSTANT_EXPONENT': '209-210',
            'TRANSDUCTION_EXPONENT': '209-210',
            'TransductionConstantPower': '209-210',
            
            # Bytes 211-212: Transduction units
            'TransductionUnits': '211-212',
            'TRANSDUCTION_UNITS': '211-212',
            'TRANSDUCTION_UNIT': '211-212',
            'TransductionUnit': '211-212',
            
            # Bytes 213-214: Trace identifier
            'TraceIdentifier': '213-214',
            'TRACE_IDENTIFIER': '213-214',
            'TRACE_ID': '213-214',
            
            # Bytes 215-216: Scalar for elevations
            'ScalarForElevations': '215-216',
            'SCALAR_FOR_ELEVATIONS': '215-216',
            'ELEVATION_SCALAR': '215-216',
            'ScalarTraceHeader': '215-216',
            
            # Bytes 217-220: Source group scalar
            'SourceGroupScalar': '217-220',
            'SOURCE_GROUP_SCALAR': '217-220',
            'SOURCE_GROUP_SCALE': '217-220',
            
            # Bytes 221-222: Source group scalar units
            'SourceGroupScalarUnits': '221-222',
            'SOURCE_GROUP_SCALAR_UNITS': '221-222',
            'SOURCE_GROUP_UNITS': '221-222',
            
            # Bytes 223-226: Group scalar
            'GroupScalar': '223-226',
            'GROUP_SCALAR': '223-226',
            'GROUP_SCALE': '223-226',
            
            # Bytes 227-228: Group scalar units
            'GroupScalarUnits': '227-228',
            'GROUP_SCALAR_UNITS': '227-228',
            'GROUP_UNITS': '227-228',
            
            # Bytes 229-232: Source coordinate X (extended)
            'SourceCoordinateXExtended': '229-232',
            'SOURCE_COORDINATE_X_EXTENDED': '229-232',
            'SOURCE_X_EXT': '229-232',
            
            # Bytes 233-236: Source coordinate Y (extended)
            'SourceCoordinateYExtended': '233-236',
            'SOURCE_COORDINATE_Y_EXTENDED': '233-236',
            'SOURCE_Y_EXT': '233-236',
            
            # Bytes 237-240: Group coordinate X (extended)
            'GroupCoordinateXExtended': '237-240',
            'GROUP_COORDINATE_X_EXTENDED': '237-240',
            'GROUP_X_EXT': '237-240',
            
            # Additional fields that may appear in segyio but are not in standard 240-byte header
            # These are likely extended or custom fields
            'SourceType': 'Extended',
            'SourceEnergyDirectionMantissa': 'Extended',
            'SourceEnergyDirectionExponent': 'Extended',
            'SourceMeasurementMantissa': 'Extended',
            'SourceMeasurementExponent': 'Extended',
            'SourceMeasurementUnit': 'Extended',
            'UnassignedInt1': 'Extended',
            'UnassignedInt2': 'Extended'
        }
        return byte_mapping
    
    def on_trace_selected(self, trace_number):
        """Handle trace selection from plot click"""
        if self.current_headers is not None:
            # Update the trace selection controls to match the clicked trace
            self.select_trace(trace_number)
    
    def display_trace_info(self, trace_number):
        """Display trace header information for the selected trace"""
        if self.current_headers is None:
            return
        
        # Clear field description when selecting a new trace
        self.field_description_text.setPlainText("")
        
        try:
            # Get the trace header data for the selected trace
            trace_data = self.current_headers.loc[trace_number]
            
            # Store current trace headers for field description lookup
            self.current_trace_headers = trace_data.to_dict()
            
            # Format the trace information
            info_text = f"TRACE HEADER INFORMATION<br>"
            info_text += f"{'='*50}<br>"
            info_text += f"CDP Number: {trace_number}<br><br>"
            
            # Display ALL trace header fields that exist in the data
            info_text += f"ALL TRACE HEADER FIELDS:<br>"
            info_text += f"{'='*50}<br>"
            
            # Get byte location mapping if needed
            byte_mapping = self.get_byte_location_mapping() if self.show_byte_locations else None
            
            for field, value in trace_data.items():
                if not pd.isna(value):
                    if self.show_byte_locations and field in byte_mapping:
                        info_text += f"<span style='text-decoration: underline; cursor: pointer;'>{field}</span> (bytes {byte_mapping[field]}): {value}<br>"
                    elif self.show_byte_locations:
                        # For fields not in mapping, show a generic byte location based on field order
                        info_text += f"<span style='text-decoration: underline; cursor: pointer;'>{field}</span> (bytes ?): {value}<br>"
                    else:
                        info_text += f"<span style='text-decoration: underline; cursor: pointer;'>{field}</span>: {value}<br>"
            
            self.trace_info_text.setHtml(info_text)
            
            # Update status bar
            self.statusBar().showMessage(f"Selected trace {trace_number}")
            
        except Exception as e:
            error_text = f"Error displaying trace {trace_number} information:\n{str(e)}"
            self.trace_info_text.setPlainText(error_text)
    
    def on_load_error(self, error_msg):
        """Handle file loading error"""
        self.file_button.setEnabled(True)
        if hasattr(self, 'progress_bar'):
            self.statusBar().removeWidget(self.progress_bar)
            del self.progress_bar
        
        QMessageBox.critical(self, "Error", f"Failed to load SEGY file:\n{error_msg}")
        self.statusBar().showMessage("Error loading file")
    
    def update_headers_display(self):
        """Update the headers display with current file information"""
        if not self.current_file_info:
            return
        
        info_text = f"FILE INFORMATION<br>"
        info_text += f"{'='*50}<br>"
        info_text += f"Filename: {self.current_file_info['filename']}<br>"
        info_text += f"Number of Traces: {self.current_file_info['n_traces']:,}<br>"
        info_text += f"Number of Samples: {self.current_file_info['n_samples']:,}<br>"
        info_text += f"Sample Rate: {self.current_file_info['sample_rate']:.2f} ms<br>"
        info_text += f"Time Window: {self.current_file_info['twt'][0]:.1f} - {self.current_file_info['twt'][-1]:.1f} ms<br><br>"
        
        # Binary headers
        info_text += f"BINARY HEADERS<br>"
        info_text += f"{'='*50}<br>"
        for key, value in self.current_bin_headers.items():
            field_name = str(key)
            # Make field names clickable for all binary header fields
            clickable_fields = ['JobID', 'LineNumber', 'ReelNumber', 'Traces', 'AuxTraces', 
                              'Interval', 'IntervalOriginal', 'Samples', 'SamplesOriginal', 
                              'Format', 'EnsembleFold', 'SortingCode', 'VerticalSum', 
                              'SweepFrequencyStart', 'SweepFrequencyEnd', 'SweepLength', 
                              'Sweep', 'SweepChannel', 'SweepTaperStart', 'SweepTaperEnd', 
                              'Taper', 'CorrelatedTraces', 'BinaryGainRecovery', 
                              'AmplitudeRecovery', 'MeasurementSystem', 'ImpulseSignalPolarity', 
                              'VibratoryPolarity', 'ExtAuxTraces', 'ExtSamples', 
                              'ExtSamplesOriginal', 'ExtEnsembleFold', 'SEGYRevision', 
                              'SEGYRevisionMinor', 'TraceFlag', 'ExtendedHeaders']
            
            # Always show descriptions (headers are always expanded)
            if field_name in clickable_fields:
                # Try to decode the value
                description = self.decode_binary_header_value(key, value)
                if description:
                    info_text += f"<span style='text-decoration: underline; cursor: pointer;'>{field_name}</span>: {value} ({description})<br>"
                else:
                    info_text += f"<span style='text-decoration: underline; cursor: pointer;'>{field_name}</span>: {value}<br>"
            else:
                # Try to decode the value
                description = self.decode_binary_header_value(key, value)
                if description:
                    info_text += f"{field_name}: {value} ({description})<br>"
                else:
                    info_text += f"{field_name}: {value}<br>"
        info_text += "<br>"
        
        # Text headers
        info_text += f"TEXT HEADERS<br>"
        info_text += f"{'='*50}<br>"
        for key, value in self.current_text_headers.items():
            info_text += f"{key}: {value}<br>"
        info_text += "<br>"
        
        self.headers_text.setHtml(info_text)
    
    def on_colormap_changed(self, colormap):
        """Handle colormap selection change - automatically update plot if data is loaded"""
        if self.current_data is not None and self.current_file_info is not None:
            # Save the new colormap setting
            self.config.update_colormap(colormap)
            # Automatically update the plot
            self.update_plot()
    
    def on_clip_enabled_changed(self, state):
        """Handle clip checkbox change - automatically update plot if data is loaded"""
        # If Clip is checked, uncheck Standard Deviation
        if self.clip_checkbox.isChecked():
            self.std_dev_checkbox.setChecked(False)
        
        if self.current_data is not None and self.current_file_info is not None:
            # Automatically update the plot
            self.update_plot()
    
    def on_std_dev_enabled_changed(self, state):
        """Handle standard deviation checkbox change - automatically update plot if data is loaded"""
        # If Standard Deviation is checked, uncheck the Clip checkbox
        if self.std_dev_checkbox.isChecked():
            self.clip_checkbox.setChecked(False)
        
        if self.current_data is not None and self.current_file_info is not None:
            # Automatically update the plot
            self.update_plot()
    
    def on_std_dev_changed(self, value):
        """Handle standard deviation value change - automatically update plot if data is loaded"""
        if self.current_data is not None and self.current_file_info is not None:
            # Only update if standard deviation is enabled
            if self.std_dev_checkbox.isChecked():
                # Automatically update the plot
                self.update_plot()
    
    def on_clip_percentile_changed(self, percentile):
        """Handle clip percentile change - automatically update plot if data is loaded"""
        if self.current_data is not None and self.current_file_info is not None:
            # Save the new clip percentile setting
            self.config.update_clip_percentile(percentile)
            # Automatically update the plot
            self.update_plot()
    
    def on_depth_mode_changed(self, state):
        """Handle depth mode toggle change - automatically update plot if data is loaded"""
        if self.current_data is not None and self.current_file_info is not None:
            # Automatically update the plot
            self.update_plot()
    
    def on_velocity_changed(self, velocity):
        """Handle velocity change - automatically update plot if data is loaded and depth mode is on"""
        if self.current_data is not None and self.current_file_info is not None:
            # Only update if depth mode is enabled
            if self.depth_mode_checkbox.isChecked():
                # Automatically update the plot
                self.update_plot()
    
    def update_plot(self):
        """Update the plot with current settings"""
        if self.current_data is not None and self.current_file_info is not None:
            clip_percentile = self.clip_spinbox.value()
            colormap = self.colormap_combo.currentText()
            depth_mode = self.depth_mode_checkbox.isChecked()
            velocity = self.velocity_spinbox.value()
            clip_enabled = self.clip_checkbox.isChecked()
            std_dev_enabled = self.std_dev_checkbox.isChecked()
            std_dev_value = self.std_dev_spinbox.value()
            
            # Save current settings
            self.config.update_clip_percentile(clip_percentile)
            self.config.update_colormap(colormap)
            
            # Update instance variables
            self.depth_mode = depth_mode
            self.velocity = velocity
            
            vm, vm1 = self.plot_widget.plot_segy_data(
                self.current_data, 
                self.current_file_info, 
                self.current_headers,
                clip_percentile, 
                colormap,
                depth_mode,
                velocity,
                clip_enabled,
                std_dev_enabled,
                std_dev_value
            )
            
            self.statusBar().showMessage(
                f"Plot updated - {clip_percentile}th percentile: {vm:.0f}, Max: {self.current_data.max():.0f}"
            )
    
    def save_plot(self):
        """Save the current plot to a file"""
        if self.current_data is None:
            return
        
        # Get save directory using last saved directory
        last_save_dir = self.config.get('last_save_directory', '')
        save_dir = QFileDialog.getExistingDirectory(
            self, "Select Directory to Save Plot", last_save_dir
        )
        
        if save_dir:
            # Update last save directory
            self.config.update_last_save_directory(save_dir)
            
            # Generate filename based on original SEGY file
            base_name = Path(self.current_file_info['filename']).stem
            save_path = os.path.join(save_dir, f"{base_name}_plot.png")
            
            try:
                # Check if full resolution is enabled
                full_resolution = self.full_res_checkbox.isChecked()
                
                if full_resolution:
                    # Show progress for full resolution export
                    self.statusBar().showMessage("Exporting full resolution plot...")
                    QApplication.processEvents()  # Update UI
                
                self.plot_widget.save_plot(save_path, full_resolution=full_resolution)
                
                if full_resolution:
                    QMessageBox.information(self, "Success", f"Full resolution plot saved to:\n{save_path}")
                    self.statusBar().showMessage(f"Full resolution plot saved to {save_path}")
                else:
                    QMessageBox.information(self, "Success", f"Plot saved to:\n{save_path}")
                    self.statusBar().showMessage(f"Plot saved to {save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save plot:\n{str(e)}")
    
    def save_shapefile(self):
        """Save CDP coordinates as a shapefile"""
        if self.current_data is None or self.current_headers is None:
            return
        
        # Get save directory using last saved directory
        last_save_dir = self.config.get('last_save_directory', '')
        save_dir = QFileDialog.getExistingDirectory(
            self, "Select Directory to Save Shapefile", last_save_dir
        )
        
        if save_dir:
            # Update last save directory
            self.config.update_last_save_directory(save_dir)
            
            # Generate filename based on original SEGY file
            base_name = Path(self.current_file_info['filename']).stem
            shapefile_path = os.path.join(save_dir, f"{base_name}_source_points.shp")
            
            try:
                self.statusBar().showMessage("Creating shapefile...")
                QApplication.processEvents()  # Update UI
                
                # Create shapefiles with source coordinates
                coord_info, point_path, line_path = self._create_cdp_shapefile(shapefile_path)
                
                # Show success message with coordinate system info
                if coord_info:
                    QMessageBox.information(self, "Success", 
                        f"Shapefiles saved:\n"
                        f"Points: {point_path}\n"
                        f"Line: {line_path}\n\n"
                        f"Coordinate System: {coord_info}")
                else:
                    QMessageBox.information(self, "Success", 
                        f"Shapefiles saved:\n"
                        f"Points: {point_path}\n"
                        f"Line: {line_path}")
                self.statusBar().showMessage(f"Shapefiles saved: {point_path}, {line_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save shapefile:\n{str(e)}")
                self.statusBar().showMessage("Shapefile export failed")
    
    def save_header_info(self):
        """Save Header Information to a text file"""
        if self.current_file_info is None or self.headers_text is None:
            return
        
        # Get save directory using last saved directory
        last_save_dir = self.config.get('last_save_directory', '')
        save_dir = QFileDialog.getExistingDirectory(
            self, "Select Directory to Save Header Information", last_save_dir
        )
        
        if save_dir:
            # Update last save directory
            self.config.update_last_save_directory(save_dir)
            
            # Generate filename based on original SEGY file with .txt extension
            base_name = Path(self.current_file_info['filename']).stem
            txt_file_path = os.path.join(save_dir, f"{base_name}.txt")
            
            try:
                # Get the header information content as plain text
                header_content = self.headers_text.toPlainText()
                
                # Write to file
                with open(txt_file_path, 'w', encoding='utf-8') as f:
                    f.write(header_content)
                
                # Show success message
                QMessageBox.information(self, "Success", 
                    f"Header information saved to:\n{txt_file_path}")
                self.statusBar().showMessage(f"Header information saved: {txt_file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save header information:\n{str(e)}")
                self.statusBar().showMessage("Header information export failed")
    
    def batch_process(self):
        """Batch process multiple SEGY files"""
        # Get file selection
        last_dir = self.config.get('last_open_directory', '')
        filenames, _ = QFileDialog.getOpenFileNames(
            self, "Select SEGY Files to Process", last_dir, "SEGY Files (*.sgy *.segy);;All Files (*)"
        )
        
        if not filenames:
            return
        
        # Get output directory
        last_save_dir = self.config.get('last_save_directory', '')
        output_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", last_save_dir
        )
        
        if not output_dir:
            return
        
        # Update last save directory
        self.config.update_last_save_directory(output_dir)
        
        # Get current settings
        colormap = self.colormap_combo.currentText()
        clip_percentile = self.clip_spinbox.value()
        full_resolution = self.full_res_checkbox.isChecked()
        depth_mode = self.depth_mode_checkbox.isChecked()
        velocity = self.velocity_spinbox.value()
        clip_enabled = self.clip_checkbox.isChecked()
        std_dev_enabled = self.std_dev_checkbox.isChecked()
        std_dev_value = self.std_dev_spinbox.value()
        
        # Create progress dialog
        progress = QProgressDialog("Processing files...", "Cancel", 0, len(filenames), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        
        # Store shapefile paths for combining
        all_point_shapefiles = []
        all_line_shapefiles = []
        processed_count = 0
        error_count = 0
        
        # Process each file
        for i, filename in enumerate(filenames):
            if progress.wasCanceled():
                break
            
            progress.setValue(i)
            progress.setLabelText(f"Processing: {os.path.basename(filename)} ({i+1}/{len(filenames)})")
            QApplication.processEvents()
            
            try:
                # Load file data
                data, trace_headers, text_headers, bin_headers, file_info = self._load_segy_file_data(filename)
                
                if data is None or file_info is None:
                    error_count += 1
                    continue
                
                base_name = Path(file_info['filename']).stem
                
                # Save plot
                plot_path = os.path.join(output_dir, f"{base_name}_plot.png")
                self._save_plot_for_file(data, file_info, plot_path, colormap, clip_percentile, full_resolution, depth_mode, velocity, clip_enabled, std_dev_enabled, std_dev_value)
                
                # Save shapefile
                shapefile_base = os.path.join(output_dir, f"{base_name}_source_points")
                point_path, line_path = self._save_shapefile_for_file(trace_headers, shapefile_base)
                if point_path:
                    all_point_shapefiles.append(point_path)
                if line_path:
                    all_line_shapefiles.append(line_path)
                
                # Save header info
                txt_path = os.path.join(output_dir, f"{base_name}.txt")
                self._save_header_info_for_file(file_info, text_headers, bin_headers, txt_path)
                
                processed_count += 1
                
            except Exception as e:
                error_count += 1
                self.statusBar().showMessage(f"Error processing {os.path.basename(filename)}: {str(e)}")
                continue
        
        progress.setValue(len(filenames))
        
        # Combine shapefiles if we have multiple files
        combined_point_path = None
        combined_line_path = None
        if len(all_point_shapefiles) > 1:
            try:
                combined_point_path = os.path.join(output_dir, "SEGY_Combined_Nav_points.shp")
                combined_line_path = os.path.join(output_dir, "SEGY_Combined_Nav_line.shp")
                self._combine_shapefiles(all_point_shapefiles, all_line_shapefiles, 
                                       combined_point_path, combined_line_path)
            except Exception as e:
                self.statusBar().showMessage(f"Error combining shapefiles: {str(e)}")
        
        # Show completion message
        message = f"Batch processing complete!\n\nProcessed: {processed_count}\nErrors: {error_count}"
        if combined_point_path and combined_line_path:
            point_name = os.path.basename(combined_point_path)
            line_name = os.path.basename(combined_line_path)
            message += f"\n\nCombined shapefiles created:\n  - {point_name}\n  - {line_name}"
        QMessageBox.information(self, "Batch Processing Complete", message)
        self.statusBar().showMessage(f"Batch processing complete: {processed_count} files processed, {error_count} errors")
    
    def show_about_dialog(self):
        """Show About dialog with program information"""
        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("About SEGY Viewer")
        dialog.setMinimumWidth(500)
        dialog.setMinimumHeight(400)
        
        # Main layout
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Program name
        program_name = QLabel(f"UNH/CCOM-JHC SEG-Y File Viewer v{__version__}")
        program_name.setStyleSheet("font-size: 16pt; font-weight: bold;")
        program_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(program_name)
        
        # Get compilation date
        compile_date = "Unknown"
        try:
            if getattr(sys, 'frozen', False):
                # Running as compiled exe
                exe_path = sys.executable
                if os.path.exists(exe_path):
                    mod_time = os.path.getmtime(exe_path)
                    compile_date = datetime.fromtimestamp(mod_time).strftime("%B %d, %Y")
            else:
                # Running as script - use script modification date
                script_path = __file__
                if os.path.exists(script_path):
                    mod_time = os.path.getmtime(script_path)
                    compile_date = datetime.fromtimestamp(mod_time).strftime("%B %d, %Y")
        except Exception:
            compile_date = "Unknown"
        
        # Compilation date
        date_label = QLabel(f"Compiled: {compile_date}")
        date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date_label.setStyleSheet("font-size: 10pt; color: gray;")
        layout.addWidget(date_label)
        
        # CCOM logo/image
        logo_path = os.path.join(os.path.dirname(__file__), "media", "CCOM.png")
        if os.path.exists(logo_path):
            logo_label = QLabel()
            pixmap = QPixmap(logo_path)
            # Scale logo to reasonable size (max width 300px)
            if pixmap.width() > 300:
                pixmap = pixmap.scaledToWidth(300, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo_label)
        
        # Author name
        author_label = QLabel("Paul Johnson")
        author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        author_label.setStyleSheet("font-size: 12pt; font-weight: bold; margin-top: 10px;")
        layout.addWidget(author_label)
        
        # Author email
        email_label = QLabel("pjohnson@ccom.unh.edu")
        email_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        email_label.setStyleSheet("font-size: 10pt; margin-top: 3px; color: #333;")
        layout.addWidget(email_label)
        
        # Institution
        institution_label = QLabel("Center for Coastal and Ocean Mapping/Joint Hydrographic Center, University of New Hampshire")
        institution_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        institution_label.setWordWrap(True)
        institution_label.setStyleSheet("font-size: 10pt; margin-top: 5px;")
        layout.addWidget(institution_label)
        
        # Grant information
        grant_text = ("This program was developed at the University of New Hampshire, "
                     "Center for Coastal and Ocean Mapping - Joint Hydrographic Center "
                     "(UNH/CCOM-JHC) under the grant NA20NOS4000196 from the National "
                     "Oceanic and Atmospheric Administration (NOAA).")
        grant_label = QLabel(grant_text)
        grant_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grant_label.setWordWrap(True)
        grant_label.setStyleSheet("font-size: 9pt; margin-top: 15px; color: #555;")
        layout.addWidget(grant_label)
        
        # License information
        license_label = QLabel("This software is released for general use under the BSD 3-Clause License.")
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        license_label.setWordWrap(True)
        license_label.setStyleSheet("font-size: 9pt; margin-top: 10px; color: #555;")
        layout.addWidget(license_label)
        
        # Add stretch to push everything up
        layout.addStretch()
        
        # OK button
        ok_button = QPushButton("OK")
        ok_button.setMaximumWidth(100)
        ok_button.clicked.connect(dialog.accept)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Show dialog
        dialog.exec()
    
    def _load_segy_file_data(self, filename):
        """Load SEGY file data without updating GUI"""
        try:
            with segyio.open(filename, ignore_geometry=True, strict=False) as f:
                # Get basic attributes
                n_traces = f.tracecount
                sample_rate = segyio.tools.dt(f) / 1000
                n_samples = f.samples.size
                twt = f.samples
                
                # Load data
                data = f.trace.raw[:]
                
                # Load headers
                bin_headers = f.bin
                text_headers = self._parse_text_header(f)
                trace_headers = self._parse_trace_headers(f, n_traces)
                
                # File information
                file_info = {
                    'filename': os.path.basename(filename),
                    'n_traces': n_traces,
                    'n_samples': n_samples,
                    'sample_rate': sample_rate,
                    'twt': twt
                }
                
                return data, trace_headers, text_headers, bin_headers, file_info
        except Exception as e:
            return None, None, None, None, None
    
    def _parse_text_header(self, segyfile):
        """Parse text header (duplicate of SegyLoaderThread method)"""
        try:
            raw_header = segyio.tools.wrap(segyfile.text[0])
            cut_header = re.split(r'C ', raw_header)[1::]
            text_header = [x.replace('\n', ' ') for x in cut_header]
            
            if not text_header:
                return {"C01": "No text header found or unsupported format"}
            
            if text_header[-1]:
                text_header[-1] = text_header[-1][:-2]
            
            clean_header = {}
            i = 1
            for item in text_header:
                key = "C" + str(i).rjust(2, '0')
                i += 1
                clean_header[key] = item
            return clean_header
        except Exception as e:
            return {"C01": f"Text header parsing failed: {str(e)}"}
    
    def _parse_trace_headers(self, segyfile, n_traces):
        """Parse trace headers (duplicate of SegyLoaderThread method)"""
        headers = segyio.tracefield.keys
        df = pd.DataFrame(index=range(1, n_traces + 1), columns=headers.keys())
        for k, v in headers.items():
            df[k] = segyfile.attributes(v)[:]
        return df
    
    def _save_plot_for_file(self, data, file_info, filename, colormap, clip_percentile, full_resolution, depth_mode=False, velocity=1500.0, clip_enabled=True, std_dev_enabled=False, std_dev_value=2.0):
        """Save plot for a specific file"""
        # Apply standard deviation clipping if enabled
        plot_data = data.copy()
        if std_dev_enabled:
            plot_data = self.plot_widget._apply_std_dev_clipping(plot_data, std_dev_value)
        
        # Calculate amplitude clipping
        if clip_enabled:
            vm = np.percentile(plot_data, clip_percentile)
            vm0 = 0
            vm1 = vm
        else:
            # No clipping - use full data range
            vm0 = plot_data.min()
            vm1 = plot_data.max()
        
        # Create extent
        n_traces = file_info['n_traces']
        twt = file_info['twt']
        
        # Convert TWT to depth if depth mode is enabled
        if depth_mode:
            # Convert TWT (ms) to depth (m): Depth = (TWT_ms / 1000) × Velocity_m/s / 2
            depth = (twt / 1000.0) * velocity / 2.0
            y_min = depth[-1]  # Last depth value (deepest)
            y_max = depth[0]   # First depth value (shallowest)
            y_label = 'Depth [m]'
        else:
            y_min = twt[-1]  # Last TWT value (deepest)
            y_max = twt[0]   # First TWT value (shallowest)
            y_label = 'TWT [ms]'
        
        extent = [1, n_traces, y_min, y_max]
        
        if full_resolution:
            # Calculate figure size based on data dimensions
            data_shape = data.shape
            fig_width = max(12, data_shape[1] * 0.01)
            fig_height = max(8, data_shape[0] * 0.002)
            fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=300)
        else:
            fig, ax = plt.subplots(figsize=(12, 6), dpi=300)
        
        # Plot the data
        im = ax.imshow(plot_data.T, cmap=colormap, vmin=vm0, vmax=vm1, 
                      aspect='auto', extent=extent)
        
        # Add labels and title
        ax.set_xlabel('CDP number')
        ax.set_ylabel(y_label)
        title = f'{file_info["filename"]}'
        if full_resolution:
            title += ' (Full Resolution)'
        ax.set_title(title)
        
        # Add colorbar
        plt.colorbar(im, ax=ax, label='Amplitude')
        
        # Save
        fig.savefig(filename, dpi=300, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        plt.close(fig)
    
    def _format_datetime_from_trace(self, trace_data):
        """Format date/time string from trace header data"""
        try:
            year = trace_data.get('YearDataRecorded', None)
            day = trace_data.get('DayOfYear', None)
            hour = trace_data.get('HourOfDay', None)
            minute = trace_data.get('MinuteOfHour', None)
            second = trace_data.get('SecondOfMinute', None)
            
            # Check if we have valid date/time data
            if year is None or pd.isna(year) or day is None or pd.isna(day):
                return None
            
            # Handle 2-digit years (assume 1900-2099 range)
            if year < 100:
                if year < 50:
                    year = 2000 + year
                else:
                    year = 1900 + year
            
            # Format as YYYY-DOY HH:MM:SS
            if hour is not None and not pd.isna(hour) and minute is not None and not pd.isna(minute):
                if second is not None and not pd.isna(second):
                    return f"{int(year)}-{int(day):03d} {int(hour):02d}:{int(minute):02d}:{int(second):02d}"
                else:
                    return f"{int(year)}-{int(day):03d} {int(hour):02d}:{int(minute):02d}:00"
            else:
                return f"{int(year)}-{int(day):03d}"
        except:
            return None
    
    def _save_shapefile_for_file(self, trace_headers, shapefile_base_path):
        """Save shapefile for a specific file, returns (point_path, line_path)"""
        try:
            import geopandas as gpd
            from shapely.geometry import Point, LineString
        except ImportError:
            try:
                import fiona
                from shapely.geometry import Point, LineString
                import json
            except ImportError:
                return None, None
        
        # Extract coordinates
        cdp_data = []
        line_coords = []
        coord_units = 2  # Default coordinate units
        
        for i, trace_num in enumerate(trace_headers.index):
            trace_data = trace_headers.loc[trace_num]
            
            # Get source coordinates
            source_x = trace_data.get('SourceX', None)
            source_y = trace_data.get('SourceY', None)
            
            if source_x is None or source_y is None:
                source_x = trace_data.get('GroupX', None)
                source_y = trace_data.get('GroupY', None)
            
            if source_x is None or source_y is None:
                source_x = trace_data.get('CDP_X', None)
                source_y = trace_data.get('CDP_Y', None)
            
            if source_x is None or source_y is None:
                continue
            
            if abs(float(source_x)) < 1e-6 and abs(float(source_y)) < 1e-6:
                continue
            
            # Get coordinate units from first valid trace
            if not cdp_data:
                coord_units = trace_data.get('CoordinateUnits', 2)
            
            source_group_scalar = trace_data.get('SourceGroupScalar', 1)
            
            # Apply SourceGroupScalar to coordinates
            if source_group_scalar > 0:
                x_coord = float(source_x) * source_group_scalar
                y_coord = float(source_y) * source_group_scalar
            elif source_group_scalar < 0:
                x_coord = float(source_x) / abs(source_group_scalar)
                y_coord = float(source_y) / abs(source_group_scalar)
            else:
                # scalar = 0 means scalar = 1
                x_coord = float(source_x)
                y_coord = float(source_y)
            
            # Convert coordinates based on units
            if coord_units == 1:  # Length (meters/feet) - treat as local coordinates
                pass  # Already in meters/feet
            elif coord_units == 2:  # Seconds of arc
                x_coord = x_coord / 3600.0  # Convert to degrees
                y_coord = y_coord / 3600.0
            elif coord_units == 3:  # Decimal degrees
                pass  # Already in degrees
            elif coord_units == 4:  # Degrees, minutes, seconds
                # For now, treat as decimal degrees (would need proper DMS parsing)
                pass  # Already in degrees
            else:
                # Unknown units - assume decimal degrees
                pass
            
            line_coords.append((x_coord, y_coord))
            
            # Get date/time for this trace
            trace_datetime = self._format_datetime_from_trace(trace_data)
            
            cdp_data.append({
                'geometry': Point(x_coord, y_coord),
                'CDP_NUM': int(trace_data.get('CDP', trace_num)),
                'TRACE_NUM': int(trace_num),
                'TRACE_SEQ': int(trace_data.get('TRACE_SEQUENCE_LINE', trace_num)),
                'SOURCE_X': x_coord,
                'SOURCE_Y': y_coord,
                'COORD_UNIT': int(coord_units),
                'SCALAR': int(source_group_scalar),
                'OFFSET': float(trace_data.get('offset', 0)),
                'ELEVATION': float(trace_data.get('SourceSurfaceElevation', 0)),
                'DATETIME': trace_datetime if trace_datetime else ''
            })
        
        if not cdp_data:
            return None, None
        
        point_path = None
        line_path = None
        
        # Create point shapefile
        try:
            gdf_points = gpd.GeoDataFrame(cdp_data)
            if coord_units in [2, 3, 4]:
                gdf_points.crs = "EPSG:4326"
            else:
                gdf_points.crs = None
            
            point_path = f"{shapefile_base_path}_points.shp"
            gdf_points.to_file(point_path)
        except:
            pass
        
        # Create line shapefile
        if len(line_coords) > 1:
            try:
                line_geometry = LineString(line_coords)
                
                # Get start and end date/time from first and last traces
                first_trace_num = trace_headers.index[0]
                last_trace_num = trace_headers.index[-1]
                first_trace_data = trace_headers.loc[first_trace_num]
                last_trace_data = trace_headers.loc[last_trace_num]
                
                start_datetime = self._format_datetime_from_trace(first_trace_data)
                end_datetime = self._format_datetime_from_trace(last_trace_data)
                
                # Create line GeoDataFrame with date/time fields
                line_attrs = {'geometry': line_geometry}
                if start_datetime:
                    line_attrs['START_DT'] = start_datetime
                else:
                    line_attrs['START_DT'] = ''
                if end_datetime:
                    line_attrs['END_DT'] = end_datetime
                else:
                    line_attrs['END_DT'] = ''
                
                gdf_line = gpd.GeoDataFrame([line_attrs])
                if coord_units in [2, 3, 4]:
                    gdf_line.crs = "EPSG:4326"
                else:
                    gdf_line.crs = None
                
                line_path = f"{shapefile_base_path}_line.shp"
                gdf_line.to_file(line_path)
            except:
                pass
        
        return point_path, line_path
    
    def _save_header_info_for_file(self, file_info, text_headers, bin_headers, filename):
        """Save header information for a specific file"""
        info_text = f"FILE INFORMATION\n"
        info_text += f"{'='*50}\n"
        info_text += f"Filename: {file_info['filename']}\n"
        info_text += f"Number of Traces: {file_info['n_traces']:,}\n"
        info_text += f"Number of Samples: {file_info['n_samples']:,}\n"
        info_text += f"Sample Rate: {file_info['sample_rate']:.2f} ms\n"
        info_text += f"Time Window: {file_info['twt'][0]:.1f} - {file_info['twt'][-1]:.1f} ms\n\n"
        
        # Binary headers
        info_text += f"BINARY HEADERS\n"
        info_text += f"{'='*50}\n"
        for key, value in bin_headers.items():
            field_name = str(key)
            description = self.decode_binary_header_value(key, value)
            if description:
                info_text += f"{field_name}: {value} ({description})\n"
            else:
                info_text += f"{field_name}: {value}\n"
        info_text += "\n"
        
        # Text headers
        info_text += f"TEXT HEADERS\n"
        info_text += f"{'='*50}\n"
        for key, value in text_headers.items():
            info_text += f"{key}: {value}\n"
        info_text += "\n"
        
        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(info_text)
    
    def _combine_shapefiles(self, point_paths, line_paths, combined_point_path, combined_line_path):
        """Combine multiple shapefiles into one"""
        try:
            import geopandas as gpd
            
            # Combine point shapefiles
            if point_paths:
                point_gdfs = []
                for path in point_paths:
                    if os.path.exists(path):
                        gdf = gpd.read_file(path)
                        # Add source file name
                        base_name = Path(path).stem.replace('_source_points_points', '')
                        gdf['SOURCE_FILE'] = base_name
                        point_gdfs.append(gdf)
                
                if point_gdfs:
                    combined_points = gpd.GeoDataFrame(pd.concat(point_gdfs, ignore_index=True))
                    # Preserve CRS from first file
                    if point_gdfs[0].crs is not None:
                        combined_points.crs = point_gdfs[0].crs
                    combined_points.to_file(combined_point_path)
            
            # Combine line shapefiles
            if line_paths:
                line_gdfs = []
                for path in line_paths:
                    if os.path.exists(path):
                        gdf = gpd.read_file(path)
                        base_name = Path(path).stem.replace('_source_points_line', '')
                        gdf['SOURCE_FILE'] = base_name
                        line_gdfs.append(gdf)
                
                if line_gdfs:
                    combined_lines = gpd.GeoDataFrame(pd.concat(line_gdfs, ignore_index=True))
                    if line_gdfs[0].crs is not None:
                        combined_lines.crs = line_gdfs[0].crs
                    combined_lines.to_file(combined_line_path)
        except Exception as e:
            raise Exception(f"Failed to combine shapefiles: {str(e)}")
    
    def _create_cdp_shapefile(self, shapefile_path):
        """Create both point and line shapefiles with CDP coordinates"""
        try:
            import geopandas as gpd
            from shapely.geometry import Point, LineString
        except ImportError:
            # Fallback to fiona and shapely if geopandas not available
            try:
                import fiona
                from shapely.geometry import Point, LineString
                import json
            except ImportError:
                raise ImportError("Required geospatial libraries not found. Please install geopandas or fiona+shapely")
        
        # Extract source coordinates from trace headers
        cdp_data = []
        line_coords = []
        
        for i, trace_num in enumerate(self.current_headers.index):
            trace_data = self.current_headers.loc[trace_num]
            
            # Get source coordinates (primary choice)
            source_x = trace_data.get('SourceX', None)
            source_y = trace_data.get('SourceY', None)
            
            # If source coordinates not available, try group coordinates
            if source_x is None or source_y is None:
                source_x = trace_data.get('GroupX', None)
                source_y = trace_data.get('GroupY', None)
            
            # If still not available, try CDP coordinates as fallback
            if source_x is None or source_y is None:
                source_x = trace_data.get('CDP_X', None)
                source_y = trace_data.get('CDP_Y', None)
            
            # Skip if no coordinates available or coordinates are essentially zero
            if source_x is None or source_y is None:
                continue
            
            # Check if coordinates are essentially zero (uninitialized)
            if abs(float(source_x)) < 1e-6 and abs(float(source_y)) < 1e-6:
                continue
            
            # Get coordinate units and scalar
            coord_units = trace_data.get('CoordinateUnits', 2)  # Default to seconds of arc
            source_group_scalar = trace_data.get('SourceGroupScalar', 1)  # Default to 1
            
            # Apply SourceGroupScalar to coordinates
            if source_group_scalar > 0:
                x_coord = float(source_x) * source_group_scalar
                y_coord = float(source_y) * source_group_scalar
            elif source_group_scalar < 0:
                x_coord = float(source_x) / abs(source_group_scalar)
                y_coord = float(source_y) / abs(source_group_scalar)
            else:
                # scalar = 0 means scalar = 1
                x_coord = float(source_x)
                y_coord = float(source_y)
            
            # Convert coordinates based on units FIRST
            if coord_units == 1:  # Length (meters/feet) - treat as local coordinates
                pass  # Already in meters
            elif coord_units == 2:  # Seconds of arc
                x_coord = x_coord / 3600.0  # Convert to degrees
                y_coord = y_coord / 3600.0
                if i < 3:
                    print(f"Debug - Trace {i+1}: After degrees conversion=({x_coord}, {y_coord})")
            elif coord_units == 3:  # Decimal degrees
                pass  # Already in degrees
            elif coord_units == 4:  # Degrees, minutes, seconds
                # For now, treat as decimal degrees (would need proper DMS parsing)
                pass  # Already in degrees
            else:
                # Unknown units - assume decimal degrees
                pass
            
            # Create point geometry
            point = Point(x_coord, y_coord)
            
            # Get date/time for this trace
            trace_datetime = self._format_datetime_from_trace(trace_data)
            
            # Collect attributes
            attributes = {
                'CDP_NUM': trace_data.get('CDP', i + 1),
                'TRACE_NUM': trace_num,
                'TRACE_SEQ': trace_data.get('TRACE_SEQUENCE_LINE', i + 1),
                'SOURCE_X': x_coord,
                'SOURCE_Y': y_coord,
                'COORD_UNIT': coord_units,
                'SCALAR': source_group_scalar,
                'OFFSET': trace_data.get('offset', 0),
                'ELEVATION': trace_data.get('ReceiverGroupElevation', 0),
                'DATETIME': trace_datetime if trace_datetime else ''
            }
            
            # Debug: Print first few coordinates to verify conversion
            if i < 3:
                print(f"Debug - Trace {i+1}: Raw=({source_x}, {source_y}), Scaled=({x_coord}, {y_coord}), Units={coord_units}")
            
            cdp_data.append({
                'geometry': point,
                **attributes
            })
            
            # Collect coordinates for line
            line_coords.append((x_coord, y_coord))
        
        if not cdp_data:
            # Check if coordinates exist but are zero
            has_zero_coords = False
            for trace_num in list(self.current_headers.index)[:5]:  # Check first 5 traces
                trace_data = self.current_headers.loc[trace_num]
                source_x = trace_data.get('SourceX', None)
                source_y = trace_data.get('SourceY', None)
                if source_x is not None and source_y is not None:
                    if abs(float(source_x)) < 1e-6 and abs(float(source_y)) < 1e-6:
                        has_zero_coords = True
                        break
            
            if has_zero_coords:
                raise ValueError("No valid coordinate data found in trace headers. Coordinates appear to be uninitialized (near zero values). This SEGY file may not contain spatial coordinate information.")
            else:
                raise ValueError("No valid coordinate data found in trace headers. Please check that SourceX/SourceY, GroupX/GroupY, or CDP_X/CDP_Y fields contain valid coordinate values.")
        
        # Determine coordinate system based on converted coordinates
        coord_system_info = None
        if coord_units in [2, 3, 4]:
            coord_system_info = "Geographic (EPSG:4326 - WGS84) - Applied SourceGroupScalar and unit conversion"
        elif self._is_utm_coordinates(x_coord, y_coord):
            coord_system_info = "UTM (EPSG:32633 - Zone 33N) - Please verify zone and coordinate system"
        else:
            coord_system_info = "Local/Unknown coordinate system - Applied SourceGroupScalar"
        
        # Create base filename without extension
        base_path = str(shapefile_path).replace('.shp', '')
        
        # Create point shapefile
        point_path = f"{base_path}_points.shp"
        try:
            gdf_points = gpd.GeoDataFrame(cdp_data)
            # Set CRS based on coordinate units
            if coord_units in [2, 3, 4]:  # Geographic coordinates
                gdf_points.crs = "EPSG:4326"  # WGS84
            elif self._is_utm_coordinates(x_coord, y_coord):
                # UTM coordinates - use a generic UTM CRS (user may need to adjust)
                gdf_points.crs = "EPSG:32633"  # UTM Zone 33N (common for Europe) - user should verify
            else:  # Local/projected coordinates
                gdf_points.crs = None  # No CRS specified
            
            # Save point shapefile
            gdf_points.to_file(point_path)
            
        except NameError:
            # Fallback using fiona
            schema = {
                'geometry': 'Point',
                'properties': {
                    'CDP_NUM': 'int',
                    'TRACE_NUM': 'int',
                    'TRACE_SEQ': 'int',
                    'SOURCE_X': 'float',
                    'SOURCE_Y': 'float',
                    'COORD_UNIT': 'int',
                    'SCALAR': 'int',
                    'OFFSET': 'float',
                    'ELEVATION': 'float',
                    'DATETIME': 'str:80'
                }
            }
            
            # Set CRS based on coordinate units
            if coord_units in [2, 3, 4]:
                crs = "EPSG:4326"  # WGS84
            elif self._is_utm_coordinates(x_coord, y_coord):
                crs = "EPSG:32633"  # UTM Zone 33N (user should verify)
            else:
                crs = None  # No CRS specified
            
            with fiona.open(point_path, 'w', driver='ESRI Shapefile', 
                          schema=schema, crs=crs) as shp:
                for item in cdp_data:
                    shp.write(item)
        
        # Create line shapefile
        line_path = f"{base_path}_line.shp"
        if len(line_coords) > 1:
            try:
                # Create line geometry connecting all points in sequence
                line_geometry = LineString(line_coords)
                
                # Get start and end date/time from first and last traces
                first_trace_num = self.current_headers.index[0]
                last_trace_num = self.current_headers.index[-1]
                first_trace_data = self.current_headers.loc[first_trace_num]
                last_trace_data = self.current_headers.loc[last_trace_num]
                
                start_datetime = self._format_datetime_from_trace(first_trace_data)
                end_datetime = self._format_datetime_from_trace(last_trace_data)
                
                line_data = [{
                    'geometry': line_geometry,
                    'LINE_ID': 1,
                    'NUM_POINTS': len(line_coords),
                    'START_TRACE': cdp_data[0]['TRACE_NUM'],
                    'END_TRACE': cdp_data[-1]['TRACE_NUM'],
                    'LENGTH_M': 0,  # Could calculate actual length if needed
                    'COORD_UNIT': coord_units,
                    'SCALAR': source_group_scalar,
                    'START_DT': start_datetime if start_datetime else '',
                    'END_DT': end_datetime if end_datetime else ''
                }]
                
                gdf_line = gpd.GeoDataFrame(line_data)
                # Set CRS based on coordinate units
                if coord_units in [2, 3, 4]:  # Geographic coordinates
                    gdf_line.crs = "EPSG:4326"  # WGS84
                elif self._is_utm_coordinates(x_coord, y_coord):
                    # UTM coordinates - use a generic UTM CRS (user may need to adjust)
                    gdf_line.crs = "EPSG:32633"  # UTM Zone 33N (common for Europe) - user should verify
                else:  # Local/projected coordinates
                    gdf_line.crs = None  # No CRS specified
                
                # Save line shapefile
                gdf_line.to_file(line_path)
                
            except NameError:
                # Fallback using fiona
                # Get start and end date/time from first and last traces
                first_trace_num = self.current_headers.index[0]
                last_trace_num = self.current_headers.index[-1]
                first_trace_data = self.current_headers.loc[first_trace_num]
                last_trace_data = self.current_headers.loc[last_trace_num]
                
                start_datetime = self._format_datetime_from_trace(first_trace_data)
                end_datetime = self._format_datetime_from_trace(last_trace_data)
                
                line_schema = {
                    'geometry': 'LineString',
                    'properties': {
                        'LINE_ID': 'int',
                        'NUM_POINTS': 'int',
                        'START_TRACE': 'int',
                        'END_TRACE': 'int',
                        'LENGTH_M': 'float',
                        'COORD_UNIT': 'int',
                        'SCALAR': 'int',
                        'START_DT': 'str:80',
                        'END_DT': 'str:80'
                    }
                }
                
                # Update line_data with date/time fields
                line_data[0]['START_DT'] = start_datetime if start_datetime else ''
                line_data[0]['END_DT'] = end_datetime if end_datetime else ''
                
                # Set CRS based on coordinate units
                if coord_units in [2, 3, 4]:
                    crs = "EPSG:4326"  # WGS84
                elif self._is_utm_coordinates(x_coord, y_coord):
                    crs = "EPSG:32633"  # UTM Zone 33N (user should verify)
                else:
                    crs = None  # No CRS specified
                
                with fiona.open(line_path, 'w', driver='ESRI Shapefile', 
                              schema=line_schema, crs=crs) as shp:
                    shp.write(line_data[0])
        
        return coord_system_info, point_path, line_path
    
    def _is_utm_coordinates(self, x, y):
        """Detect if coordinates appear to be UTM meters based on typical ranges"""
        # UTM coordinates typically have these characteristics:
        # - X (Easting): 100,000 to 900,000 meters (varies by zone)
        # - Y (Northing): 0 to 10,000,000 meters (varies by hemisphere)
        # - Both values are typically large positive numbers
        # - X values are usually 6 digits, Y values can be 7 digits
        
        # Check if coordinates are in typical UTM ranges
        utm_x_range = 100000 <= abs(x) <= 900000
        utm_y_range = 0 <= y <= 10000000
        
        # Additional checks for UTM characteristics
        large_numbers = abs(x) > 10000 and y > 10000
        reasonable_precision = len(str(int(abs(x)))) >= 5 and len(str(int(y))) >= 5
        
        # UTM coordinates are typically not in degree ranges
        not_degrees = not (-180 <= x <= 180 and -90 <= y <= 90)
        
        # Check for invalid seconds of arc (too large for valid degrees)
        # Valid seconds of arc range: -648,000 to +648,000 (for ±180°)
        invalid_seconds_arc = abs(x) > 648000 or abs(y) > 648000
        
        return (utm_x_range and utm_y_range) or (large_numbers and reasonable_precision and not_degrees and invalid_seconds_arc)
    
    def closeEvent(self, event):
        """Handle application close event"""
        # Save configuration when closing
        self.config.save_config()
        event.accept()


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("SEGY File Viewer")
    
    window = SegyGui()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
