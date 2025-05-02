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

#### v0.2.0 - 2025-03-21

`GpibDevice.close()` renamed to `GpibDevice.close_connection()`, and converted to a no-op. This is a breaking change bugfix.

Previous versions of this method called `pyvisa.Resource.close()`, which made the device permanently
inaccessible to the underlying running instance of VISA on the host machine (i.e., the process on the computer that actually talks to the external device).
PyVisa does not handle this gracefully, so the user ends up being confronted with inexplicable errors and essentially a spinlock whenever attempting to use any PyVisa method after closing any resource.

Critically, `GpibDevice.close()` / `GpibDevice.close_connection()` was/is called at exit time when `GpibDevice` is used as a context manager.
This means that upon leaving the context manager code block, PyVisa will always be left in an unusable state on all versions below 0.2.0.
(NOTE: Using the `GpibDevice` class without a context manager will work as expected with no problems on these versions, as long as the user does not manually call `GpibDevice.close()`.)

RECOMMENDATION: All users SHOULD upgrade to version >= 0.2.0. Users using `GpibDevice` as a context manager MUST upgrade to version >= 0.2.0.

#### v0.2.1 - 2025-03-27

BUGFIX: Modified requirements in pyproject.toml to work with traditional pip install, not just UV.

#### v0.2.2 - 2025-03-27

BUGFIX: `SpectrumAnalyzerHP8563E.find` will create a null logger if not given a logger

#### v0.3.0 - 2025-03-27

`SpectrumAnalyzerHP8563E.find` will now raise an exception if it can't connect. This is a breaking change.

#### v0.3.1 - 2025-03-27

`Turntable.find` will now raise an exception if it can't connect. This is a breaking change.

#### v0.3.2 - 2025-05-02

Handle edge case where turntable stops exactly 0.1 deg from commanded position [See Issue #6](https://github.com/msu-ssc/lems-anechoic/issues/6)
