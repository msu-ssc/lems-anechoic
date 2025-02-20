import enum


class Frequency(enum.Enum):
    TEN_GHZ = "P"
    ONE_GHZ = "Q"
    ONE_HUNDRED_MHZ = "R"
    TEN_MHZ = "S"
    ONE_MHZ = "T"
    ONE_HUNDRED_KHZ = "U"
    TEN_KHZ = "V"
    ONE_KHZ = "W"
    EXECUTE = "Z"


class FM(enum.Enum):
    OFF = "6"
    THIRTY_KHZ = "5"
    ONE_HUNDRED_KHZ = "4"
    THREE_HUNDRED_KHZ = "3"
    ONE_MHZ = "2"
    THREE_MHZ = "1"
    TEN_MHZ = "0"


class ALC(enum.Enum):
    RF_OFF = "0"
    INT_NORMAL = "1"
    INT_PLUS_TEN_RANGE = "3"
    XTAL_NORMAL = "5"
    XTAL_PLUS_TEN_RANGE = "7"
    MTR_NORMAL = "="
    MTR_PLUS_TEN_RANGE = "?"


class OutputLevelRange(enum.Enum):
    ZERO_DBM = "0"
    NEGATIVE_10_DBM = "1"
    NEGATIVE_20_DBM = "2"
    NEGATIVE_30_DBM = "3"
    NEGATIVE_40_DBM = "4"
    NEGATIVE_50_DBM = "5"
    NEGATIVE_60_DBM = "6"
    NEGATIVE_70_DBM = "7"
    NEGATIVE_80_DBM = "8"
    NEGATIVE_90_DBM = "9"
    NEGATIVE_100_DBM = ":"
    NEGATIVE_110_DBM = "-"


class OutputLevelVernier(enum.Enum):
    PLUS_THREE_DB = "0"
    PLUS_TWO_DB = "1"
    PLUS_ONE_DB = "2"
    ZERO_DB = "3"
    NEGATIVE_1_DB = "4"
    NEGATIVE_2_DB = "5"
    NEGATIVE_3_DB = "6"
    NEGATIVE_4_DB = "7"
    NEGATIVE_5_DB = "8"
    NEGATIVE_6_DB = "9"
    NEGATIVE_7_DB = ":"
    NEGATIVE_8_DB = "-"
    NEGATIVE_9_DB = "\\"
    NEGATIVE_10_DB = "_"


class AM(enum.Enum):
    OFF = "0"
    HUNDRED_PERCENT = "2"
    THIRTY_PERCENT = "3"


class StatusByte(enum.IntFlag):
    CRYSTAL_OVEN_COLD = 0x80
    RSV_REQUEST_SERVICE = 0x40
    OUT_OF_RANGE_FREQUENCY = 0x20
    RF_OFF = 0x10
    NOT_PHASE_LOCKED = 0x08
    LEVEL_UNCAL = 0x04
    FM_OVER_MOD = 0x02
    PLUS_10_DBM_OVER_RANGE = 0x01


b = StatusByte(0xff)
print(f"{b=!r}")
print(f"{b=!s}")