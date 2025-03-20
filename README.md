# lems-anechoic
LEMS anechoic chamber test scripts

> [!CAUTION]  
> Remember, CUI/ITAR/etc. data (including code/config files/design docs) does not belong on GitHub at all.

### Provenance

Code for `terminal.py` and `controller.py` originally written by Jody Caudill. No documentation of this code exists.
.

### Changelog

#### v0.1.0 - Before March 2025

Earliest working version. This is the version that was used in the pre-TVAC ETU testing for LEMS-A3.

#### v0.1.1 - 2025-03-12

Bugfix to require `send_set_command` to be azimuth 0 and elevation 0

#### v0.1.2 - 2025-03-20

Bugfix:  `SpectrumAnalyzerHP8563E.find()` will no longer crash if no GPIB was connected.