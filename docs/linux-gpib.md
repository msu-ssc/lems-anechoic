# GPIB spectrum-analyzer setup on Linux

These instructions configure `lems-anechoic` to communicate with an HP 8563E
spectrum analyzer through a Keysight 82357B USB/GPIB adapter on Linux.

Linux support for the turntable is separate and has not been verified.

## Proven configuration

This procedure was verified with:

- Ubuntu 24.04.3 LTS, x86-64
- kernel `7.0.0-28-generic`
- UEFI Secure Boot enabled
- Keysight IO Libraries Suite for Linux `21.3.94` (2026)
- IVI VISA shared components `7.0.0`
- Keysight 82357B, USB ID `0957:0718`
- HP 8563E at GPIB primary address 18
- PyVISA `1.14.1`

The existing application discovered `GPIB0::18::INSTR` and connected without a
code change. A direct `CF?` query returned:

```text
3.90000000E8
```

which is `390000000 Hz`.

Keysight documents Ubuntu 24.04 with kernel 6.8 as a tested combination. The
newer kernel above is outside that published test matrix, but the Keysight DKMS
modules built, loaded under Secure Boot, and communicated successfully.

## Driver architecture

Use Keysight IO Libraries Suite for Linux:

```text
lems-anechoic
  -> PyVISA
  -> Keysight VISA (/opt/keysight/iolibs/libvisa.so)
  -> Keysight 82357 driver (Kt82357Run)
  -> Keysight 82357B
  -> HP 8563E
```

Do not install or load the open-source `agilent_82357a`/`linux-gpib` driver at
the same time. Both stacks would try to control the same USB interface. The
open-source stack was not needed for the proven configuration.

## Install Keysight IO Libraries Suite

Skip the installation if `/opt/keysight/iolibs/libvisa.so` already exists and
`lsusb -t` reports `Driver=Kt82357Run`.

### Download

Download the current **Linux x64** version of Keysight IO Libraries Suite from:

<https://www.keysight.com/find/iosuite>

Do not download the legacy Keysight Instrument Control Bundle. That bundle is
Windows-only; the Linux IO Libraries Suite is a separate download.

The version tested on 2026-07-27 was:

```text
IOLibrariesSuite-21.3.94-linux-x64.run
```

Its SHA-256 was:

```text
cafad1e017a5fa03a81e8dc7cbbad160ede55532ea2c456d89be5f3f31ab30ab
```

Use the filename and checksum published by Keysight if a newer release is
available.

### Run the installer

Disconnect the 82357B from USB and close instrument-control software. From the
directory containing the downloaded installer, verify the checksum and launch
it:

```bash
sha256sum IOLibrariesSuite-21.3.94-linux-x64.run
chmod +x IOLibrariesSuite-21.3.94-linux-x64.run
sudo ./IOLibrariesSuite-21.3.94-linux-x64.run
```

The graphical setup wizard opens:

1. On the welcome screen, click **Forward**.
2. On **Select Components**, leave the default selections enabled.
3. Expand **IO Interfaces** and verify that **USB-GPIB** is selected. This is
   the essential interface for the 82357B.
4. The default Connection Expert, Interactive IO, IO Monitor, and Direct
   Connect utilities may remain selected.
5. Continue through the ordinary confirmation screens.
6. When upgrading, allow the installer to remove the previous IO Libraries
   Suite before installing the new version.
7. If a dialog recommends a reboot, acknowledge it but wait for the main
   installer to finish.
8. When the main wizard reports that setup has finished, click **Finish**.
9. Reboot the computer.
10. After logging in, reconnect the 82357B.

The installer adds Keysight libraries, services, udev rules, a `kt-iols`
group, and DKMS kernel modules. Follow any kernel-compatibility or Secure
Boot/MOK instructions shown on the computer.

## Configure PyVISA

Tell PyVISA to use the Keysight VISA implementation:

```bash
export PYVISA_LIBRARY=/opt/keysight/iolibs/libvisa.so
```

Add that line to `~/.profile` to make it persistent, then log out and back in
or reboot. On the proven installation, `libvisa.so` resolves to Keysight's
`libktvisa32.so`.

Confirm the setting in a new login session:

```bash
printenv PYVISA_LIBRARY
```

Expected output:

```text
/opt/keysight/iolibs/libvisa.so
```

## Verify the installation

Connect the 82357B to the computer and its GPIB cable to the powered-on
HP 8563E. Confirm that the analyzer's GPIB primary address is 18.

The following checks are useful after installation:

```bash
lsusb -d 0957:0718
lsusb -t
lsmod | grep -E 'kt82357(Run|Boot)'
dkms status | grep -E 'kt82357(Run|Boot)'
id -nG
readlink -f /opt/keysight/iolibs/libvisa.so
```

Expected highlights include:

```text
ID 0957:0718 Agilent Technologies, Inc. 82357B
Driver=Kt82357Run
kt82357Run
kt82357Boot
kt-iols
/opt/keysight/iolibs/libktvisa32.so
```

For IO Libraries Suite `21.3.94`, these services were also active:

```bash
systemctl is-active \
  io-ds.service \
  KeysightDistributedInfrastructureService.service \
  KeysightIOControlService.service
```

If the current user is not in `kt-iols`, add the user and then fully log out
and back in or reboot:

```bash
sudo usermod -aG kt-iols "$(id -un)"
```

Keysight Connection Expert can provide an additional graphical check that the
adapter and GPIB instrument are visible.

## Verify lems-anechoic

From the repository root, run:

```bash
uv run test-connection.py
```

The proven spectrum-analyzer result was:

```text
✅ Connected to Spectrum Analyzer. Serial: 3310A01144, GPIB address: GPIB0::18::INSTR
```

The test also checks the turntable. A turntable discovery failure does not
invalidate the spectrum-analyzer result; Linux turntable support has not been
verified.

The HP 8563E does not respond to the common SCPI `*IDN?` query. The application
identifies this analyzer using the non-mutating `CF?` query.

## Troubleshooting

### PyVISA cannot find a VISA library

Check:

```bash
printenv PYVISA_LIBRARY
test -e /opt/keysight/iolibs/libvisa.so
readlink -f /opt/keysight/iolibs/libvisa.so
```

`PYVISA_LIBRARY` should name the Keysight library. Do not select the PyVISA-Py
backend with `@py` for this configuration; its GPIB support requires the
separate open-source `linux-gpib` stack.

### The adapter is absent

Check:

```bash
lsusb -d 0957:
journalctl -k --no-pager | grep -i -E '0957|82357|Kt82357'
```

The operational 82357B USB product ID is `0957:0718`. The adapter initially
uses a boot-stage identity while its firmware loads, then re-enumerates and
binds to `Kt82357Run`.

### The Keysight module is missing after a kernel update

Check:

```bash
uname -r
dkms status | grep kt82357
modinfo kt82357Run
journalctl -k --no-pager | grep -i -E 'kt82357|module|secure'
```

`modinfo kt82357Run` should show a `vermagic` matching the running kernel. With
Secure Boot enabled, it should also show a valid signer. Repair or rerun the
official Keysight installer if the module was not built for the current
kernel.

### The analyzer is not discovered

Verify:

- the HP 8563E is powered on;
- both GPIB cable ends are secure;
- the analyzer's GPIB primary address is 18;
- no other process holds an exclusive VISA/GPIB lock; and
- `PYVISA_LIBRARY` selects Keysight VISA.

## References

- [Keysight IO Libraries Suite downloads](https://www.keysight.com/find/iosuite)
- [Keysight IO Libraries Suite help](https://www.keysight.com/gw/en/lib/resources/help-files/io-libraries-suite-online-help.html)
- [PyVISA documentation](https://pyvisa.readthedocs.io/)
