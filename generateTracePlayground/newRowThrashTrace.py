# thermal_attack_trace.py
# Generates a DRAMSim3 trace to maximize power: bank-interleaved, row-conflict, write-heavy.

# ---- Config from your DRAMSim3 file ----
TCK_NS     = 0.94        # not used here, but good to remember (DDR4-2133)
BANKGROUPS = 4           # 2 bits (Bg)
BANKS_PER_GROUP = 4      # 2 bits (Ba)
COLUMNS    = 1024        # 10 bits total
ROWS       = 131072      # 17 bits
BL         = 8           # choose 3 low column bits as burst offset
# Address mapping: rochrababgco (MSB→LSB): Row | ColHi | Rank | Bank | Bg | ColLo

# ---- Trace shape knobs ----
filename        = "thermal_attackv3.trace"
num_rounds      = 20000        # increase for longer run (think 100k–1M+)
cycle_step      = 4            # tightest legal CAS-to-CAS short (tCCD_S ≈ 4)
write_phase_len = 20000        # cycles per phase before flipping R/W
write_ratio     = 0.75         # fraction of ops that are WR during write phase
start_cycle     = 10

# ---- Bit slicing per mapping (choose CO=3 LSBs for BL8; remaining column bits go to CH) ----
COL_LO_BITS = 3                   # BL8 -> 3 LSBs are burst offset
COL_HI_BITS = 10 - COL_LO_BITS    # remaining column bits
BG_BITS     = 2
BA_BITS     = 2
RA_BITS     = 0                   # single rank
ROW_BITS    = 17

# Lay out bit positions from LSB upward: Co(3) | Bg(2) | Ba(2) | Ra(0) | Ch(7) | Row(17)
CO_SHIFT  = 0
BG_SHIFT  = CO_SHIFT + COL_LO_BITS
BA_SHIFT  = BG_SHIFT + BG_BITS
RA_SHIFT  = BA_SHIFT + BA_BITS
CH_SHIFT  = RA_SHIFT + RA_BITS
ROW_SHIFT = CH_SHIFT + COL_HI_BITS

# Simple address constructor for rochrababgco
def addr_of(row, bg, ba, col):
    # col has 10 bits: split into hi/lo
    col_lo = col & ((1 << COL_LO_BITS) - 1)
    col_hi = col >> COL_LO_BITS
    a = ((row & ((1 << ROW_BITS) - 1)) << ROW_SHIFT) \
        | ((col_hi & ((1 << COL_HI_BITS) - 1)) << CH_SHIFT) \
        | ((0) << RA_SHIFT) \
        | ((ba  & ((1 << BA_BITS) - 1)) << BA_SHIFT) \
        | ((bg  & ((1 << BG_BITS) - 1)) << BG_SHIFT) \
        | ((col_lo & ((1 << COL_LO_BITS) - 1)) << CO_SHIFT)
    return f"0x{a:08x}"

# Two rows per bank to force row-conflicts
ROW0 = 0x00001
ROW1 = 0x1FFFF  # far apart to guarantee different rows
COL  = 0        # keep column small; power is dominated by ACT/PRE + bus toggling

with open(filename, "w") as f:
    cycle = start_cycle
    phase_write = True
    in_phase_start = cycle

    # Round-robin over bank-groups and banks, toggling row in each bank
    toggle = [[0 for _ in range(BANKS_PER_GROUP)] for _ in range(BANKGROUPS)]

    rounds = 0
    while rounds < num_rounds:
        for bg in range(BANKGROUPS):
            for ba in range(BANKS_PER_GROUP):
                # alternate rows in this (bg,ba) to force ACT→PRE→ACT...
                use_row = ROW1 if toggle[bg][ba] else ROW0
                toggle[bg][ba] ^= 1

                a = addr_of(use_row, bg, ba, COL)

                # pick op based on phase and ratio
                if phase_write:
                    # write-heavy
                    op = 'W' if (rounds % 100) < int(100 * write_ratio) else 'R'
                else:
                    # read phase (still include some writes)
                    op = 'R' if (rounds % 100) < 80 else 'W'

                # DRAMSim3 default text format: <time> <address> <op>
                f.write(f"{cycle} {a} {op}\n")
                cycle += cycle_step

        rounds += 1

        # Flip between write/read phases every write_phase_len cycles
        if cycle - in_phase_start >= write_phase_len:
            phase_write = not phase_write
            in_phase_start = cycle

print(f"Wrote {filename} with ~{num_rounds * BANKGROUPS * BANKS_PER_GROUP} requests.")
print(f"Final time: {cycle} cycles")
