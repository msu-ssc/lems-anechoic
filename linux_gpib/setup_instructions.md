# Keysight 82357B GPIB on Linux

These instructions establish a minimal, standalone connection from Linux
through a Keysight 82357B USB/GPIB adapter to an HP 8563E spectrum analyzer.
The verification sends the read-only analyzer query `CF?` and checks for a
numeric response near 390 MHz.

This proof of concept does not use or modify the rest of the `lems-anechoic`
package.

## Proven configuration

The procedure was verified on:

- Ubuntu 24.04.3 LTS, x86-64
- kernel `7.0.0-28-generic`
- UEFI Secure Boot enabled
- Keysight IO Libraries Suite for Linux `21.3.94` (2026)
- IVI VISA shared components `7.0.0`
- Keysight 82357B, USB ID `0957:0718`
- HP 8563E at GPIB primary address 18
- PyVISA `1.14.1` under Python 3.10

The verified response was:

```text
3.90000000E8
```

which parses as `390000000 Hz`.

Keysight's documentation lists Ubuntu 24.04 with kernel 6.8 as a tested
combination. The newer kernel above is outside that published test matrix, but
the Keysight DKMS modules built, loaded under Secure Boot, and communicated
successfully on this computer.

## Selected driver architecture

Use Keysight IO Libraries Suite for Linux:

```text
PyVISA or VISA C/C++
  -> Keysight VISA (/opt/keysight/iolibs/libvisa.so)
  -> Keysight 82357 driver (Kt82357Run)
  -> Keysight 82357B
  -> HP 8563E
```

Do not install or load the open-source `agilent_82357a`/`linux-gpib` driver at
the same time. Both stacks would try to control the same USB interface.

The open-source stack remains a fallback, but it was not needed for this
working configuration.

## 1. Install Keysight IO Libraries Suite

Skip this section if `/opt/keysight/iolibs/libvisa.so` already exists and
`lsusb -t` already reports `Driver=Kt82357Run`.

### Download

Download the Linux version of Keysight IO Libraries Suite from the official
page:

<https://www.keysight.com/find/iosuite>

Keysight's current releases may use one unified installer. Follow the release
notes accompanying the downloaded Linux build.

As of 2026-07-27, Keysight's current Linux release is IO Libraries Suite 2026,
build `21.3.94`, released 2026-07-10. It uses a unified Linux x64 installer.
Keysight lists support for CentOS 7.4-9.4, Red Hat Enterprise Linux 7.4-10.1,
selected Ubuntu releases from 18.04 through 26.04, and Debian 12.x.

The exact tested unified installer and its SHA-256 are:

```text
cafad1e017a5fa03a81e8dc7cbbad160ede55532ea2c456d89be5f3f31ab30ab
  IOLibrariesSuite-21.3.94-linux-x64.run
```

This locally calculated hash matches the checksum published by Keysight.

The previous working version retained on the test computer uses two
installers:

```text
IOLSPrerequisites-21.1.185-linux-x64.run
IOLibrariesSuiteMain-21.1.185-linux-x64.run
```

Their recorded SHA-256 hashes are:

```text
25a241a71879a00c724540533b5395fc9b1e2891ab63202c33b457f0bcc1801e
  IOLSPrerequisites-21.1.185-linux-x64.run
e58a7766cf5215216983525baa8fc04d1e580cdb5f724509d2b763b8d1680d3b
  IOLibrariesSuiteMain-21.1.185-linux-x64.run
```

Use these hashes only for build `21.1.185`. A newer official build will have
different filenames and hashes.

Build `21.1.185` is a general Linux x64 release rather than an Ubuntu-specific
package. Its published support list includes CentOS, Red Hat Enterprise Linux,
and Ubuntu, but not Debian. Debian 12 support was added in IO Libraries Suite
2025 Update 1, which also replaced the two-installer layout with one unified
installer.

### Install the current unified release

For Linux build `21.3.94`:

```bash
sha256sum IOLibrariesSuite-21.3.94-linux-x64.run
chmod +x IOLibrariesSuite-21.3.94-linux-x64.run
sudo ./IOLibrariesSuite-21.3.94-linux-x64.run
```

The graphical setup wizard opens.

1. Disconnect the 82357B from USB and close instrument-control software.
2. On the welcome screen, click **Forward**.
3. On **Select Components**, leave the default selections enabled.
4. Expand **IO Interfaces** and verify that **USB-GPIB** is checked. This is
   the essential interface for the Keysight 82357B.
5. The default GUI utilities—Connection Expert, Interactive IO, IO Monitor,
   and Direct Connect—may remain selected. Connection Expert and Interactive
   IO are particularly useful for discovery and manual verification.
6. Click **Forward** and continue through the ordinary confirmation screens.
7. When upgrading, allow the unified installer to remove the previous IO
   Libraries Suite before it installs the new suite.
8. If an information dialog says that some settings require a reboot, click
   **OK** to acknowledge it. Do not reboot while the main installer is still
   running.
9. Wait for the main wizard to report that setup has finished, then click
   **Finish**.
10. Reboot the computer.
11. After login, reconnect the 82357B and verify the installation as described
    below.

The default interface selection also includes interfaces not required for this
proof of concept, such as LAN, USBTMC/USB, remote interfaces, ASRL, and
PCI-GPIB. Leaving the defaults selected is the tested upgrade procedure and
avoids accidentally omitting a dependency. A future clean-install experiment
may establish a smaller supported selection.

### Install the verified older two-installer release

1. Disconnect the 82357B from USB. Leave the analyzer powered on or off; it
   does not matter during software installation.
2. Close instrument-control software.
3. Make the downloaded installer or installers executable.
4. Run the prerequisite installer first and the main installer second.
5. Reboot, as directed by Keysight.
6. Reconnect the 82357B after the reboot.

For the verified `21.1.185` two-installer build, a text-mode installation is:

```bash
chmod +x IOLSPrerequisites-21.1.185-linux-x64.run
chmod +x IOLibrariesSuiteMain-21.1.185-linux-x64.run

sudo ./IOLSPrerequisites-21.1.185-linux-x64.run --mode text
sudo ./IOLibrariesSuiteMain-21.1.185-linux-x64.run --mode text
sudo reboot
```

Omit `--mode text` to use the graphical installer.

The installer adds system packages, services, udev rules, a `kt-iols` group,
Keysight VISA/SICL libraries, and DKMS kernel modules. On a kernel newer than
Keysight's tested matrix, the installer may display a compatibility warning.

With Secure Boot enabled, confirm that the DKMS modules are signed by an
enrolled key. Follow any MOK enrollment prompt produced by the installer or
Ubuntu during reboot.

## 2. Verify the driver and services

After rebooting and reconnecting the adapter:

```bash
lsusb -d 0957:0718
lsusb -t
lsmod | grep -E 'kt82357(Run|Boot)'
dkms status | grep -E 'kt82357(Run|Boot)'
systemctl is-active \
  io-ds.service \
  KeysightDistributedInfrastructureService.service \
  KeysightIOControlService.service
id -nG
```

Expected highlights:

```text
ID 0957:0718 Agilent Technologies, Inc. 82357B
Driver=Kt82357Run
kt82357Run
kt82357Boot
active
active
active
kt-iols
```

These are the three Keysight services directly observed as active with build
`21.3.94`.

Also verify the VISA library:

```bash
readlink -f /opt/keysight/iolibs/libvisa.so
```

On the proven installation this resolves to Keysight's `libktvisa32.so`.

Configure PyVISA to use the Keysight implementation:

```bash
export PYVISA_LIBRARY=/opt/keysight/iolibs/libvisa.so
```

Add that export to `~/.profile` to make it persistent for future login
sessions, then log out and back in or reboot. The tested computer already had
the equivalent setting below from its original 2025 installation:

```bash
export PYVISA_LIBRARY=/opt/keysight/iolibs/libktvisa32.so
```

`libvisa.so` resolves to `libktvisa32.so` on the tested installation. The
`libvisa.so` name is preferable in new instructions because it is the
installer-managed VISA entry point rather than the implementation-specific
filename.

If the current user is not in `kt-iols`, add the user and then reboot or fully
log out and back in:

```bash
sudo usermod -aG kt-iols "$(id -un)"
```

## 3. Create the isolated Python environment

From the repository root:

```bash
uv venv linux_gpib/.venv

UV_CACHE_DIR=linux_gpib/.uv_cache \
  uv pip install \
  --python linux_gpib/.venv/bin/python \
  -r linux_gpib/requirements.txt
```

This installs PyVISA only inside `linux_gpib/.venv`.

## 4. Query the HP 8563E

Connect the 82357B to the computer and the GPIB cable to the powered-on
HP 8563E. Confirm that the analyzer's GPIB primary address is 18.

Run:

```bash
linux_gpib/.venv/bin/python linux_gpib/pyvisa_cf_query.py
```

Expected output:

```text
Loading VISA library: /opt/keysight/iolibs/libvisa.so
Opening resource: GPIB0::18::INSTR
Sending query: CF?
Raw response: '3.90000000E8\n'
Parsed center frequency: 3.9e+08 Hz
PASS: GPIB query returned the expected center frequency
```

If the instrument uses a different GPIB address:

```bash
linux_gpib/.venv/bin/python linux_gpib/pyvisa_cf_query.py \
  --resource GPIB0::ADDRESS::INSTR
```

If the analyzer is intentionally set to a different center frequency:

```bash
linux_gpib/.venv/bin/python linux_gpib/pyvisa_cf_query.py \
  --expected-hz EXPECTED_FREQUENCY_IN_HZ
```

The HP 8563E does not respond to the usual SCPI `*IDN?` query. `CF?` is the
appropriate non-mutating connectivity test for this instrument.

### Verify the existing lems-anechoic application

With `PYVISA_LIBRARY` set as described above, the existing application code
works without modification:

```bash
uv run test-connection.py
```

Observed spectrum-analyzer result:

```text
✅ Connected to Spectrum Analyzer. Serial: 3310A01144, GPIB address: GPIB0::18::INSTR
```

The same run reported that it could not find the turntable. Turntable discovery
is independent of the Keysight VISA/GPIB spectrum-analyzer path and does not
indicate a failure of this setup.

## 5. Optional direct VISA C++ verification

The C++ probe avoids Python entirely:

```bash
g++ -Wall -Wextra -Wpedantic -O2 \
  -I/opt/keysight/iolibs/include \
  linux_gpib/visa_cf_query.cpp \
  -L/opt/keysight/iolibs \
  -Wl,-rpath,/opt/keysight/iolibs \
  -lvisa \
  -o linux_gpib/visa_cf_query

./linux_gpib/visa_cf_query
```

Keysight's installed `visatype.h` includes the C++ header `<cstdint>`, so use
`g++` and the `.cpp` source. Compiling the same source as C with `gcc` fails.

## Troubleshooting

### PyVISA cannot find a VISA library

First confirm that the standard PyVISA environment variable is present:

```bash
printenv PYVISA_LIBRARY
```

For this setup it should name the Keysight library:

```text
/opt/keysight/iolibs/libvisa.so
```

The standalone proof script also loads that path explicitly, making the proof
independent of the caller's environment. On the proven host, `pyvisa-info` did
not reliably identify the IVI binary library automatically even though the
explicit Keysight library and the environment-variable selection both worked.

Do not select the PyVISA-Py backend with `@py` for this setup. PyVISA-Py's GPIB
support requires the separate open-source linux-gpib stack.

### The adapter is absent

Check:

```bash
lsusb -d 0957:
journalctl -k --no-pager | grep -i -E '0957|82357|Kt82357'
```

The operational 82357B USB product ID is `0957:0718`. The adapter initially
uses a boot-stage identity while its firmware loads, then re-enumerates as
`0957:0718` and binds to `Kt82357Run`.

### The Keysight module is missing after a kernel update

Check the running kernel and DKMS state:

```bash
uname -r
dkms status | grep kt82357
modinfo kt82357Run
journalctl -k --no-pager | grep -i -E 'kt82357|module|secure'
```

`modinfo kt82357Run` should show a `vermagic` matching the running kernel. With
Secure Boot enabled it should also show a valid signer. Re-run the official
Keysight installer or repair the DKMS installation if the module was not built
for the current kernel.

### VISA opens but `CF?` times out

Verify:

- the HP 8563E is powered on;
- both GPIB cable ends are secure;
- the analyzer's GPIB address is 18;
- no other process holds an exclusive VISA/GPIB lock; and
- the query is exactly `CF?`, not `*IDN?`.

The probe timeout can be increased:

```bash
linux_gpib/.venv/bin/python linux_gpib/pyvisa_cf_query.py \
  --timeout-ms 10000
```

## References

- Keysight IO Libraries Suite downloads:
  <https://www.keysight.com/find/iosuite>
- Keysight IO Libraries Suite Linux help:
  <https://www.keysight.com/gw/en/lib/resources/help-files/io-libraries-suite-online-help.html>
- Keysight IO Libraries Suite 2025 Update 1 Linux release notes:
  <https://www.keysight.com/content/dam/keysight/en/doc/gate/release-notes/Release-Notes-IOLS-2025-U1-Linux.htm>
- linux-gpib 4.3.7:
  <https://sourceforge.net/projects/linux-gpib/files/linux-gpib%20for%203.x.x%20and%202.6.x%20kernels/4.3.7/>
- PyVISA-Py GPIB installation notes:
  <https://pyvisa.readthedocs.io/projects/pyvisa-py/en/latest/installation.html>
