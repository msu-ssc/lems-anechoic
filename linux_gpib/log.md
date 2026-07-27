# Linux GPIB proof-of-concept log

## Goal

Establish a reproducible, Linux-native connection through the connected
Keysight 82357B USB/GPIB adapter to the powered-on HP 8563E spectrum analyzer.
The proof of success is sending `CF?` and receiving a numeric response expected
to be approximately `390000000`.

This work is intentionally independent of the rest of the `lems-anechoic`
codebase.

## Change-control boundary

- Read-only inspection, web research, downloads, workspace-local files, and
  workspace-local builds/tests are permitted without additional confirmation.
- System package installation/removal, kernel-module or firmware changes, udev
  and permission changes, services, system configuration, privileged
  state-changing commands, and reboots require explicit user confirmation.

## 2026-07-27

### 12:30 EDT — Experiment workspace initialized

- Confirmed that `linux_gpib/` did not previously exist.
- Created this log before beginning host discovery.
- No packages have been installed and no system configuration has been changed.

### 12:31 EDT — Initial host and hardware inventory

Read-only commands used:

```text
uname -a
uname -m
sed -n '1,160p' /etc/os-release
lsusb
lsusb -t
lsmod
mokutil --sb-state
command -v <candidate GPIB/VISA tools>
dpkg-query -W <filtered for relevant packages>
find /dev <filtered for gpib/usbtmc nodes>
journalctl -k -n 300 <filtered for the adapter>
```

Findings:

- Host: x86-64 Ubuntu 24.04.3 LTS ("noble").
- Running kernel:
  `7.0.0-28-generic #28~24.04.1-Ubuntu SMP PREEMPT_DYNAMIC`.
- UEFI Secure Boot is enabled.
- The adapter is visible on USB bus 3, port 6:
  - USB vendor/product ID: `0957:0718`
  - Product: `82357B`
  - Manufacturer: `Agilent Technologies, Inc.`
  - Serial: `MY55153510`
- The USB interface is already bound to kernel driver `Kt82357Run`.
- Keysight modules already loaded:
  - `kt82357Run` (two users)
  - `kt82357Boot` (zero users)
- The kernel journal shows a clean attachment at 12:15:

  ```text
  usb 3-6: New USB device found, idVendor=0957, idProduct=0718
  usb 3-6: Product: 82357B ()
  usb 3-6: Manufacturer: Agilent Technologies, Inc.
  usb 3-6: SerialNumber: MY55153510
  Kt82357Run 3-6:1.0: Kt82357Run now attached to Kt82357Run-0
  ```

- Package `visa-shared` version `7.0.0-0` is already installed.
- No `gpib_config`, `ibtest`, `ibstatus`, `ibfind`, `pyvisa-info`,
  `visa-conf`, or `visaconf` executable was found on `PATH`.
- No `/dev/gpib*` or `/dev/usbtmc*` node was found. This is not necessarily
  an error for the Keysight proprietary driver path, which may expose a
  differently named node.
- Plain `lsusb` returned `unable to initialize libusb: -99`, although
  `lsusb -t` and the kernel journal could see the device. This needs
  explanation; it may reflect interaction with the installed Keysight USB
  driver or a broader libusb issue.

Interpretation:

The computer appears to have at least part of Keysight's Linux driver stack
already installed. The immediate next step is to inventory that installation
and identify whether a usable VISA shared library/resource manager is already
present. Installing a competing `linux-gpib` stack before resolving this could
create a USB-driver conflict, so no installation will be attempted yet.

No system state or configuration was changed during this inventory.

### 12:33 EDT — Existing Keysight installation inventory

Additional read-only inspection covered kernel-module metadata, DKMS state,
installed IVI packages, Keysight files and documentation, dynamic-library
linkage, systemd unit files, udev rules, group membership, and available
compiler tools.

Findings:

- A full Keysight IO Libraries Suite installation is present at
  `/opt/keysight/iolibs`.
- Installed suite version: `21.1.185`, identified by its bundled documentation
  as "Keysight IO Libraries Suite 2025 (for Linux)".
- Major installed components include:
  - Keysight VISA (`/opt/keysight/iolibs/libvisa.so`)
  - Keysight SICL
  - Connection Expert and Interactive IO web applications
  - USB-GPIB discovery agents and services
  - 82357 kernel-driver source and DKMS configuration
  - VISA headers and a bundled SICL test utility
- The IVI VISA shared-component packages are installed at version `7.0.0`:
  `libivivisa0`, `libivivisa-utilities0`, `libivivisa-confmgr0`,
  `libivivisa0-devel`, and `visa-shared`.
- `/opt/keysight/iolibs/libvisa.so` resolves to Keysight's
  `libktvisa32.so`.
- The current user, `mayo`, is already a member of the installer's `kt-iols`
  group.
- Udev rule `/etc/udev/rules.d/40-iols-kernels-group.rules` grants the
  `kt-iols` group access to USB devices bound to the Keysight 82357 boot/run
  drivers.
- The Keysight DKMS modules are installed for kernels `6.14.0-37`,
  `6.17.0-29`, `6.17.0-40`, and the running `7.0.0-28`.
- The running modules are PKCS#7-signed with this computer's enrolled
  Secure-Boot module key and have a matching `7.0.0-28-generic` version
  signature.
- GCC 14.2 and GNU Make 4.3 are already available, so a workspace-local C
  VISA probe can be built without installing anything.
- Keysight's bundled documentation explicitly supports Ubuntu 24.04, but
  lists kernel 6.8 as the tested configuration. This machine's kernel 7.0 is
  newer than the documented test matrix. Nevertheless, its Keysight modules
  have built, loaded, and attached to the adapter.
- Running Keysight's `vifind` utility inside the restricted experiment
  sandbox produced repeated `Operation not permitted` connection errors.
  This is consistent with the sandbox's isolated devices/network and is not
  yet evidence of a host-side VISA failure.

Conclusion:

The proprietary Keysight path is already installed to the point where a direct
communication test is justified before any installation or configuration
change. A local VISA C probe will be created and compiled, then run with access
to the host hardware.

No system state or configuration was changed.

### 12:35 EDT — Option research and first probe build

Primary/reference sources reviewed:

- Keysight IO Libraries Suite help:
  <https://www.keysight.com/gw/en/lib/resources/help-files/io-libraries-suite-online-help.html>
- Keysight IO Libraries Suite 2025 Update 1 Linux release notes:
  <https://www.keysight.com/content/dam/keysight/en/doc/gate/release-notes/Release-Notes-IOLS-2025-U1-Linux.htm>
- Keysight IO Libraries Suite downloads:
  <https://www.keysight.com/gb/en/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637.html>
- linux-gpib 4.3.7 release files and README:
  <https://sourceforge.net/projects/linux-gpib/files/linux-gpib%20for%203.x.x%20and%202.6.x%20kernels/4.3.7/>
- PyVISA-Py GPIB installation documentation:
  <https://pyvisa.readthedocs.io/projects/pyvisa-py/en/latest/installation.html>

Options considered:

1. **Existing Keysight VISA stack (selected first).**
   Keysight documents Linux support for GPIB and USB-GPIB, including Ubuntu
   24.04. The installed stack already recognizes this adapter and exposes the
   standard VISA API needed by this experiment. It requires no system change
   for an initial test.
2. **Open-source in-tree GPIB kernel driver plus linux-gpib userspace
   (fallback).**
   linux-gpib 4.3.7 explains that GPIB drivers entered the Linux kernel from
   6.13 onward, and provides the userspace library/configuration tools. This
   Ubuntu kernel contains GPIB driver source in its headers but did not ship
   loadable `gpib_common` or `agilent_82357a` modules. This route would
   therefore require building/installing modules and replacing the driver
   currently bound to the adapter.
3. **Out-of-tree linux-gpib kernel and userspace stack (last fallback).**
   Release 4.3.7 states support through kernel 6.17. The running kernel is 7.0,
   so this is both more invasive and outside that release's stated test range.
4. **PyVISA-Py on linux-gpib.**
   This is a Python layer over option 2 or 3, not an independent hardware
   solution. It becomes useful only after a linux-gpib driver/userspace stack
   works.

Created `linux_gpib/visa_cf_query.cpp`, a standalone VISA program which:

- defaults to `GPIB0::18::INSTR`;
- opens the Keysight/IVI VISA resource manager;
- sets a 5-second I/O timeout;
- sends only the read-only query `CF?`;
- reads and prints the raw response; and
- verifies that the response begins with a numeric value.

First build attempt:

```text
gcc ... linux_gpib/visa_cf_query.c ... -lvisa
```

Result:

```text
/opt/keysight/iolibs/include/visatype.h:74:10:
fatal error: cstdint: No such file or directory
```

Cause: the installed Keysight `visatype.h` uses the C++ `<cstdint>` header
under GCC, even when included from C. The source was renamed `.cpp` and built
with `g++`:

```text
g++ -Wall -Wextra -Wpedantic -O2 \
  -I/opt/keysight/iolibs/include \
  linux_gpib/visa_cf_query.cpp \
  -L/opt/keysight/iolibs \
  -Wl,-rpath,/opt/keysight/iolibs \
  -lvisa \
  -o linux_gpib/visa_cf_query
```

The C++ build completed with no warnings or errors. The next action is to run
this compiled probe against the host hardware. Compilation created only the
workspace-local executable; no system state or configuration was changed.

### 12:36 EDT — Proof of communication succeeded

The compiled probe was run outside the restricted device sandbox so it could
access the host's existing Keysight services and USB/GPIB adapter:

```text
./linux_gpib/visa_cf_query
```

Complete output:

```text
Opening VISA resource manager
Opening GPIB0::18::INSTR with a 5000 ms timeout
Writing query: CF?
Wrote 3 bytes
Raw response (13 bytes): 3.90000000E8

Parsed center frequency: 390000000 Hz
```

Result: **success**.

This proves the full path:

```text
standalone program
  -> Keysight VISA
  -> Keysight 82357 Linux kernel driver
  -> Keysight 82357B USB/GPIB adapter
  -> GPIB address 18
  -> HP 8563E
```

The returned value is exactly the expected `390000000 Hz`.

No packages were installed, services changed, modules manually loaded, device
permissions altered, or system configuration modified. The machine's
pre-existing Keysight IO Libraries Suite installation was already functional.

### 12:39 EDT — Independent PyVISA proof succeeded

Created an isolated Python 3.10 virtual environment:

```text
uv venv linux_gpib/.venv
```

The first PyVISA install attempt tried to use uv's default cache under
`~/.cache/uv` and was rejected by the workspace sandbox as read-only. Retried
with a cache confined to the experiment directory:

```text
UV_CACHE_DIR=linux_gpib/.uv_cache \
  uv pip install \
  --python linux_gpib/.venv/bin/python \
  pyvisa==1.14.1
```

The sandbox could not resolve PyPI, so the same command was retried with
permitted network access. It installed only:

```text
pyvisa==1.14.1
typing-extensions==4.16.0
```

Created:

- `requirements.txt`, pinning PyVISA 1.14.1;
- `pyvisa_cf_query.py`, a standalone Python probe; and
- `.gitignore`, excluding the local virtual environment, uv cache, and
  compiled C++ binary.

The Python probe explicitly loads
`/opt/keysight/iolibs/libvisa.so`, opens `GPIB0::18::INSTR`, sends `CF?`, and
checks the result against 390 MHz. This avoids relying on automatic selection
of a VISA implementation.

Command:

```text
linux_gpib/.venv/bin/python linux_gpib/pyvisa_cf_query.py
```

Complete output:

```text
Loading VISA library: /opt/keysight/iolibs/libvisa.so
Opening resource: GPIB0::18::INSTR
Sending query: CF?
Raw response: '3.90000000E8\n'
Parsed center frequency: 3.9e+08 Hz
PASS: GPIB query returned the expected center frequency
```

Result: **success**.

Read-only host postcondition checks showed:

- all five checked Keysight services were active:
  `KeysightInstrumentIoService`, `KeysightIOControlService`,
  `KeysightInteractiveIOService`, `KeysightIOMonitorService`, and
  `KeysightRemoteConnectionExpertService`;
- host `lsusb` identified `0957:0718` as the Agilent 82357B;
- `lsusb -t` showed `Driver=Kt82357Run`;
- `kt82357Run` and `kt82357Boot` were loaded; and
- the host user belongs to both `kt-iols` and `usbtmc`.

The original installers used on this machine are still present in the user's
Downloads directory:

```text
IOLSPrerequisites-21.1.185-linux-x64.run
IOLibrariesSuiteMain-21.1.185-linux-x64.run
```

Recorded SHA-256 hashes:

```text
25a241a71879a00c724540533b5395fc9b1e2891ab63202c33b457f0bcc1801e
  IOLSPrerequisites-21.1.185-linux-x64.run
e58a7766cf5215216983525baa8fc04d1e580cdb5f724509d2b763b8d1680d3b
  IOLibrariesSuiteMain-21.1.185-linux-x64.run
```

System package logs show the IVI shared components were installed on
2026-02-05, consistent with those downloads. No new host package or
configuration change was made in this experiment.

### 12:42 EDT — Reproducible instructions and final validation

Ran each retained Keysight installer with `--help` only. This confirmed the
exact product/version strings and the supported `--mode text` option without
performing an installation:

```text
Keysight IO Libraries Suite Prerequisites 2025 21.1.185
Keysight IO Libraries Suite 2025 21.1.185
```

`linux_gpib/.venv/bin/pyvisa-info` reported PyVISA 1.14.1 but did not report an
automatically discovered IVI binary library. The successful proof script
therefore continues to pass the installed Keysight library explicitly:

```text
/opt/keysight/iolibs/libvisa.so
```

Created `setup_instructions.md` with:

- the selected Keysight architecture and rejected/fallback alternatives;
- the exact known-working software and hardware baseline;
- official download references;
- the retained installer names and SHA-256 hashes;
- installation and reboot steps reconstructed from Keysight's bundled and
  online documentation;
- driver, DKMS, Secure Boot, service, group, and USB verification commands;
- isolated PyVISA environment setup;
- both Python and C++ proof procedures; and
- targeted troubleshooting guidance.

Validation performed:

- `git diff --check -- linux_gpib` returned no whitespace errors.
- `pyvisa_cf_query.py --help` completed successfully.
- After the Python probe explicitly closed both its instrument and resource
  manager, the standalone C++ probe was run again.
- The second C++ run again returned `3.90000000E8` / `390000000 Hz`.
  This confirms the device can be cleanly reopened after the Python test.

Final result: the requested proof of concept is working through both direct
Keysight VISA C++ and isolated PyVISA.

Host system changes made during this experiment: **none**.

Workspace-local changes consist of the `linux_gpib/` experiment files, compiled
probe, Python virtual environment, and download cache.

### Follow-up — VISA discovery compatibility

The application does not open only a known hard-coded resource:
`SpectrumAnalyzerHP8563E.find()` first calls `ResourceManager.list_resources()`.
Tested that specific discovery behavior with the installed Keysight library:

```text
linux_gpib/.venv/bin/python -c \
  'import pyvisa; rm = pyvisa.ResourceManager("/opt/keysight/iolibs/libvisa.so"); print(rm.list_resources()); rm.close()'
```

Result:

```text
('GPIB0::18::INSTR',)
```

This confirms that the existing application's discovery loop can see the HP
8563E when it uses the Keysight VISA library. No host state or configuration
was changed.

### Follow-up — Installer platform and current-version check

Checked Keysight's current official Linux release pages on 2026-07-27.

- The retained `21.1.185` `.run` files are generic Linux x86-64 installers,
  not Ubuntu/Debian-specific packages.
- Keysight's support list for that exact 2025 release includes CentOS
  7.4-9.4, Red Hat Enterprise Linux 7.4-9.4, and selected Ubuntu releases
  through 24.04. Debian is not listed for that release.
- IO Libraries Suite 2025 Update 1 added Debian 12 support and changed from a
  prerequisite-plus-main pair to one unified Linux installer.
- Search-index text initially made build `21.3.293`, released 2026-04-30,
  appear to be the current Linux release. The live platform tabs later showed
  that this is the Windows build; the Linux build is recorded in the
  correction below.
- The 2026 published support list includes CentOS 7.4-9.4, Red Hat Enterprise
  Linux 7.4-10.1, selected Ubuntu releases through 26.04, and Debian 12.x.
- Keysight publishes SHA-256
  `CAFAD1E017A5FA03A81E8DC7CBBAD160EDE55532EA2C456D89BE5F3F31AB30AB`
  for the current Linux x64 installer.

Sources:

- <https://www.keysight.com/find/iosuite>
- <https://www.keysight.com/br/pt/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637/keysight-io-libraries-suite-2026-for-linux.html>
- <https://www.keysight.com/de/de/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637/keysight-io-libraries-suite-2025-for-linux.html>
- <https://www.keysight.com/de/de/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637/keysight-io-libraries-suite-2025-update-1-for-linux.html>

No files were downloaded and no host state or configuration was changed during
this version check.

### Follow-up — Correct current Keysight download

Verified that the Keysight "Instrument Control Bundle Download" is not the
correct Linux download. Keysight marks that bundle as no longer up to date,
Windows-only, and retained for legacy support; its last release contains IO
Libraries Suite 2023 Update 1 plus BenchVue and Command Expert.

For this GPIB setup, the correct current selection is:

```text
IO Libraries Suite Downloads
  -> Linux
  -> Keysight IO Libraries Suite 2026 for Linux
  -> Download Linux x64 IOLS
```

Sources:

- <https://www.keysight.com/zz/en/lib/software-detail/computer-software/keysight-instrument-control-bundle-download-1184883.html>
- <https://www.keysight.com/find/iosuite>
- <https://www.keysight.com/de/de/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637/keysight-io-libraries-suite-2026-for-linux.html>

No file was downloaded and no system state or configuration was changed.

### Follow-up — Live upgrade to IO Libraries Suite 2026

The user downloaded the current Linux installer:

```text
~/Downloads/iols-new/IOLibrariesSuite-21.3.94-linux-x64.run
```

The live Keysight page clarified a platform-tab ambiguity in indexed web
results:

- Linux: build `21.3.94`, released 2026-07-10
- Windows: build `21.3.293`, released 2026-04-30

The Linux filename is therefore correct.

The user launched the installer with the 82357B disconnected. The graphical
wizard displayed:

1. **Setup - Keysight IO Libraries Suite 2026** welcome screen.
2. **Select Components**, with the default selections enabled.

Observed default component tree:

- New GUI
  - Connection Expert
  - Interactive IO
  - IO Monitor
  - Direct Connect
- IO Interfaces
  - LAN
  - USB
  - Remote Interfaces, including ASRL, USB, and GPIB
  - ASRL
  - PCI-GPIB
  - USB-GPIB
- VXI, VXI-GPIB, and PXI were not selected/available.

Decision: retain the default selections and explicitly verify that
**USB-GPIB** remains checked. USB-GPIB is the essential interface for the
82357B; the extra default components are acceptable for this guinea-pig
upgrade and provide useful discovery/diagnostic tools.

At this checkpoint, the assistant had run no command and the user had not yet
advanced beyond component selection.

### Follow-up — Upgrade completed and reboot requested

The user continued through ordinary confirmation screens without recording
each one. The unified installer then:

1. automatically uninstalled the previous IO Libraries Suite;
2. installed IO Libraries Suite Main;
3. displayed a 100% progress dialog recommending a system reboot;
4. displayed an information dialog explaining that some system settings do
   not take effect immediately; and
5. reached the completion screen stating that setup had finished.

The reboot information dialog's **OK** button only acknowledged the message;
the user waited for the main installer to finish before clicking **Finish**.
The user then rebooted the computer.

These observed steps have been incorporated into `setup_instructions.md`.

### Follow-up — IO Libraries Suite 2026 post-upgrade proof

The user explicitly authorized read-only post-reboot commands and repeating
the non-mutating `CF?` query.

Read-only commands covered:

```text
uname -a
lsusb
lsusb -t
systemctl list-units / is-active
lsmod
dkms status
dpkg-query
find /opt/keysight/iolibs
version.txt and manifest.json inspection
id -nG mayo
readlink -f /opt/keysight/iolibs/libvisa.so
modinfo kt82357Run
journalctl -k -b
PyVISA list_resources()
sha256sum of the downloaded unified installer
the standalone PyVISA CF? probe
git diff validation for linux_gpib/
```

Some initial commands were intentionally attempted inside the restricted
workspace sandbox. In that environment, `lsusb` reported
`unable to initialize libusb: -99`, `systemctl` could not connect to the
system bus, and VISA/device access was unavailable. Those read-only checks
were repeated with explicit host access after the user authorized them and
then succeeded. This confirms that the earlier libusb error was a sandbox
artifact rather than a host USB problem.

An initial `dpkg-query` used package globs that did not match the actual IVI
package names. A subsequent filtered full package query correctly found the
installed `libivivisa*` and `visa-shared` packages.

After reboot, read-only inspection confirmed:

- `/opt/keysight/iolibs/version.txt` reports `21.3.94`;
- the locally calculated installer SHA-256 is
  `cafad1e017a5fa03a81e8dc7cbbad160ede55532ea2c456d89be5f3f31ab30ab`,
  matching Keysight's published checksum;
- `lsusb` identifies `0957:0718 Agilent Technologies, Inc. 82357B`;
- `lsusb -t` shows the adapter bound to `Kt82357Run`;
- `kt82357Run` and `kt82357Boot` are loaded;
- DKMS reports both Keysight modules installed for the running
  `7.0.0-28-generic` kernel;
- `kt82357Run` has matching `7.0.0-28-generic` version metadata and a PKCS#7
  signature from this computer's enrolled Secure Boot module-signing key;
- IVI VISA shared components remain at version `7.0.0`;
- `/opt/keysight/iolibs/libvisa.so` resolves to
  `/opt/keysight/iolibs/libktvisa32.so`;
- the host user remains in `kt-iols` and `usbtmc`; and
- the Keysight discovery, distributed-infrastructure, and IO-control services
  are active.

`dkms status` also printed deprecated-configuration warnings for the Keysight
DKMS files and an unrelated missing-source error for an old NVIDIA DKMS entry.
The relevant results were nevertheless unambiguous: both `kt82357Boot/1.0`
and `kt82357Run/1.0` are installed for `7.0.0-28-generic`.

The current boot's kernel journal shows a clean adapter attachment:

```text
usb 3-6: New USB device found, idVendor=0957, idProduct=0718
usb 3-6: Product: 82357B ()
usb 3-6: Manufacturer: Agilent Technologies, Inc.
usb 3-6: SerialNumber: MY55153510
Kt82357Run 3-6:1.0: Kt82357Run now attached to Kt82357Run-0
```

Keysight VISA resource discovery returned:

```text
('GPIB0::18::INSTR',)
```

The isolated PyVISA probe was then run against the upgraded installation:

```text
linux_gpib/.venv/bin/python linux_gpib/pyvisa_cf_query.py
```

Complete result:

```text
Loading VISA library: /opt/keysight/iolibs/libvisa.so
resource='GPIB0::18::INSTR'
Opening resource: GPIB0::18::INSTR
instrument=<'GPIBInstrument'('GPIB0::18::INSTR')>
type(instrument)=<class 'pyvisa.resources.gpib.GPIBInstrument'>
Sending query: CF?
Raw response: '3.90000000E8\n'
Parsed center frequency: 3.9e+08 Hz
PASS: GPIB query returned the expected center frequency
```

Result: **success**. The current Keysight IO Libraries Suite 2026 Linux build
`21.3.94` works with the 82357B and HP 8563E on this Ubuntu 24.04 / kernel 7.0
/ Secure Boot configuration.

The installer and reboot changed host system state under the user's direct
control. The assistant's post-reboot commands were read-only and the final
query was non-mutating.
