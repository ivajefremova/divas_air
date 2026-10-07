import glob
import pandas as pd

CLASSES = {
    "widebody": """A306 A30B A310 A332 A333 A338 A339 A342 A343 A345 A346 A359 A35K A388
                   A3ST A400 B744 B748 B762 B763 B764 B772 B773 B77L B77W B778 B779
                   B788 B789 B78X MD11 DC10 IL96 C17 K35R IL76""",
    "narrowbody": """A318 A319 A320 A321 A19N A20N A21N B731 B732 B733 B734 B735 B736 B737
                     B738 B739 B37M B38M B39M B3XM B752 B753 BCS1 BCS3 B712 MD82 MD83
                     MD87 MD88 MD90 C919""",
    "regional": """E170 E175 E75L E75S E190 E195 E290 E295 CRJ1 CRJ2 CRJ7 CRJ9 CRJX
                   RJ85 RJ1H SU95 F100 F70 E135 J328""",
    "turboprop": """AT43 AT45 AT46 AT72 AT73 AT75 AT76 DH8A DH8B DH8C DH8D SF34 SB20
                    D328 JS41 F50 ATP D228 SW4 CL2T C130 C30J C27J AN26""",
    "bizjet": """GLF4 GLF5 GLF6 GL5T GL7T GLEX G280 GALX CL30 CL35 CL60 C25A C25B C25C
                 C25M C500 C510 C525 C550 C560 C56X C650 C680 C68A C700 C750 E35L E50P
                 E55P E545 E550 F2TH F900 FA7X FA8X FA50 FA6X H25B H25C LJ35 LJ40 LJ45
                 LJ60 LJ75 PRM1 HDJT PC24 BE40 SF50 EA50 GA5C GA6C GA7C C55B FA10""",
    "light": """P180 PC12 TBM7 TBM8 TBM9 BE20 BE30 BE9L B350 C208 C172 C182 C210 P28A
                DA40 DA42 DA62 PA46 M600 SR22 P68 DV20 C150 C152 P208 P06T M20P RV7 RV8 T206 SF25 VL3 C82T SVNH
                     TEXA OSCR P28U BE33 BE36 BE58 EFOX C72R PA34 S22T CTLN KP5 PRIM
                     NG5 TOBA ECHO P46T""",
    "helicopter": """A139 A169 A189 A109 A119 AW09 EC30 EC35 EC45 EC55 EC75 EC25 AS50
                     AS55 AS65 B06 B407 B412 B429 S76 S92 H160 NH90 EH10 R44 R22 B430 B505""",
}
code_to_class = {c: k for k, v in CLASSES.items() for c in v.split()}

df = pd.concat(pd.read_parquet(f, columns=["icao24", "type"])
               for f in glob.glob("data/processed/adsblol_fco_*.parquet"))
ac = df.drop_duplicates("icao24")
counts = ac.type.value_counts()

out = pd.DataFrame({"typecode": counts.index, "aircraft_seen": counts.values})
out["size_class"] = out.typecode.map(code_to_class).fillna("other")
out.to_csv("data/reference/aircraft_types.csv", index=False)

print(out.size_class.value_counts().to_string())
unmapped = out[out.size_class == "other"]
print(f"\n{len(unmapped)} codes unmapped ({unmapped.aircraft_seen.sum()} aircraft):")
print(" ".join(unmapped.typecode))