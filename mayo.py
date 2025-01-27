import logging
logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)s: %(message)s', 
    datefmt='%Y-%m-%d %H:%M:%S', 
    level=logging.DEBUG
)
logging.info("MAYO")

import pyvisa

rm = pyvisa.ResourceManager()
print(f"{rm=}")
# print(rm.list_resources())

resources = list(rm.list_resources())

print(f"{resources=}")

# exit(1)

for index, resource in enumerate(resources):
    print(f"\n******************** {index=} {resource=} ********************")
    try:
        inst = rm.open_resource(resource)
        result = inst.query("CF?")
        print(f"{resource=} {inst=} {result=}")
    except Exception as exc:
        print(f"{exc=} for {resource=}")
        # import traceback
        # traceback.print_exc()
        # break
        continue