# lems-anechoic
LEMS anechoic chamber test scripts

> [!CAUTION]  
> Remember, CUI/ITAR/etc. data (including code/config files/design docs) does not belong on GitHub at all.

## Provenance

Code for `terminal.py` and `controller.py` originally written by Jody Caudill. No documentation of this code exists. This code is no longer used for any purpose.

All other code written by David Mayo.

## Installation

### General

You must be on a Windows computer that you have administrative rights to.

[Install uv](https://docs.astral.sh/uv/getting-started/installation/), which is a Python package manager. (Alternately, you can do all of this with your Python of choice, if you know what you're doing.)

### GPIB control (for spectrum analyzer)

The spec-an is controlled via GPIB, which requires a bunch of drivers that you need to install manually.
- Install [NI-Visa](bin/ni-visa_23.5_online.exe).
- Reboot computer.
- Install Keysight Instrument Control Bundle. A current link is [here](https://www.keysight.com/us/en/lib/software-detail/computer-software/keysight-instrument-control-bundle-download-1184883.html), but it might expire. You can Google for the current link. Specifically, install the "IO Libraries Suite" with the GUI.
- Reboot computer.
- Run the program "Keysight Connection Expert" to confirm that you can see any attached GPIB device.

### USB/UART control (for turntable)
- Plug in the UART cable (aka "the turntable USB cable")
- Find the device in device manager
- Install the [CP210x Universal Windows Driver](bin/CP210x_Universal_Windows_Driver.zip).

### Verification

Run `uv run test-connection.py` to verify connection.

## Changelog

### v0.1.0 - Before March 2025

Earliest working version. This is the version that was used in the pre-TVAC ETU testing for LEMS-A3.

### v0.1.1 - 2025-03-12

Bugfix to require `send_set_command` to be azimuth 0 and elevation 0

### v0.1.2 - 2025-03-20

Bugfix:  `SpectrumAnalyzerHP8563E.find()` will no longer crash if no GPIB was connected.

### v0.2.0 - 2025-03-21

`GpibDevice.close()` renamed to `GpibDevice.close_connection()`, and converted to a no-op. This is a breaking change bugfix.

Previous versions of this method called `pyvisa.Resource.close()`, which made the device permanently
inaccessible to the underlying running instance of VISA on the host machine (i.e., the process on the computer that actually talks to the external device).
PyVisa does not handle this gracefully, so the user ends up being confronted with inexplicable errors and essentially a spinlock whenever attempting to use any PyVisa method after closing any resource.

Critically, `GpibDevice.close()` / `GpibDevice.close_connection()` was/is called at exit time when `GpibDevice` is used as a context manager.
This means that upon leaving the context manager code block, PyVisa will always be left in an unusable state on all versions below 0.2.0.
(NOTE: Using the `GpibDevice` class without a context manager will work as expected with no problems on these versions, as long as the user does not manually call `GpibDevice.close()`.)

RECOMMENDATION: All users SHOULD upgrade to version >= 0.2.0. Users using `GpibDevice` as a context manager MUST upgrade to version >= 0.2.0.

### v0.2.1 - 2025-03-27

BUGFIX: Modified requirements in pyproject.toml to work with traditional pip install, not just UV.

### v0.2.2 - 2025-03-27

BUGFIX: `SpectrumAnalyzerHP8563E.find` will create a null logger if not given a logger

### v0.3.0 - 2025-03-27

`SpectrumAnalyzerHP8563E.find` will now raise an exception if it can't connect. This is a breaking change.

### v0.3.1 - 2025-03-27

`Turntable.find` will now raise an exception if it can't connect. This is a breaking change.

### v0.3.2 - 2025-05-02

Handle edge case where turntable stops exactly 0.1 deg from commanded position [See Issue #6](https://github.com/msu-ssc/lems-anechoic/issues/6)

### v0.3.3 - 2025-05-07
Add convenience 'find' function to spec_an module

### v0.3.4 - 2025-05-07
#16 - Add several spec-an commands

### v0.3.5 - 2025-05-07
#12 - Create method to get/set spec an configs into/from an archival format

### v0.3.6 - 2025-05-08
Add ability to set/query sweep time

### v0.3.7 - 2025-06-09
Add multiple grid functionality (issue #22)

### v0.3.8 - 2025-06-09
Add sweep parameters to each get_* definition in spec_an.py (issue #19)

### v0.3.9 - 2025-06-09
Add "Confirm" Option to Turntable Codebase (issue #8)

### v0.3.10 - 2025-08-14
Update documentation to include installation instructions

### v0.3.11 - 2025-08-14
Speed up spec-an centering process

### v0.3.12 - 2025-08-14
Add validation of polarization to Experiment.run()

### v0.3.13 - 2025-08-14
Add multiple cuts at once.
Add sound to experiment running.

### v0.3.14 - 2025-08-14
Add move timeout

### v0.4.0 - 2025-08-27
Version to be used for LEMS-A3 flight unit testing

### v0.4.1 - 2025-08-28
Apply entire config to spec an when running an experiment, not just some of it

### v0.4.2 - 2025-08-28
Prompt user to verify polarization when running experiments

### v0.4.3 - 2025-08-28
Widen azimuth margin

### v0.4.4 - 2025-08-28
BUGFIX: Widen azimuth margin correctly