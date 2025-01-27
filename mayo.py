import logging
logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)s: %(message)s', 
    datefmt='%Y-%m-%d %H:%M:%S', 
    # level=logging.DEBUG,
    level=logging.INFO,
)
logging.info("MAYO")

import sys
logging.debug(f"{sys.path=}")
logging.debug(f"{sys.executable=}")

import pyvisa

rm = pyvisa.ResourceManager()
print(f"{rm=}")
print(f"{rm.visalib=}")
print(f"{rm.visalib=}")
# print(rm.list_resources())

resources = list(rm.list_resources())

print(f"{resources=}")

# resources.append("GPIB0::13::INSTR")

# exit(1)

for index, resource in enumerate(resources):
    print(f"\n******************** {index=} {resource=} ********************")
    try:
        inst = rm.open_resource(resource)
        result = inst.query("*IDN?", delay=0.1)
        print(f"{resource=} {inst=} {result=}")
    except Exception as exc:
        print(f"{exc=} for {resource=}")
        # import traceback
        # traceback.print_exc()
        # break
        continue

# name = "GPIB0::13::INSTR"
# inst = rm.open_resource(resource)
# result = inst.query("CF?")
