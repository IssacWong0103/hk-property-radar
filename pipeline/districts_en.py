"""HK area name localisation + mapping to the official 18 District Council districts.

The first-hand sales register (17) reports fine-grained locales in Chinese
(e.g. 西半山). We (a) translate them to English for YR, and (b) roll each up to
one of Hong Kong's official 18 districts, so the dashboard can show a real
18-district view built from data we already have.
"""
from __future__ import annotations

# The official 18 districts, grouped by region, in a sensible display order.
DISTRICTS_18 = [
    ("Central & Western", "HK Island"),
    ("Wan Chai", "HK Island"),
    ("Eastern", "HK Island"),
    ("Southern", "HK Island"),
    ("Yau Tsim Mong", "Kowloon"),
    ("Sham Shui Po", "Kowloon"),
    ("Kowloon City", "Kowloon"),
    ("Wong Tai Sin", "Kowloon"),
    ("Kwun Tong", "Kowloon"),
    ("Kwai Tsing", "New Territories"),
    ("Tsuen Wan", "New Territories"),
    ("Tuen Mun", "New Territories"),
    ("Yuen Long", "New Territories"),
    ("North", "New Territories"),
    ("Tai Po", "New Territories"),
    ("Sha Tin", "New Territories"),
    ("Sai Kung", "New Territories"),
    ("Islands", "New Territories"),
]
DISTRICT_REGION = {name: region for name, region in DISTRICTS_18}

# Chinese launch-area -> (English label, official 18-district)
AREA = {
    # ---- HK Island ----
    "香港仔及鴨脷洲": ("Aberdeen & Ap Lei Chau", "Southern"),
    "鴨脷洲": ("Ap Lei Chau", "Southern"),
    "薄扶林": ("Pok Fu Lam", "Southern"),
    "赤柱": ("Stanley", "Southern"),
    "壽臣山及淺水灣": ("Shouson Hill & Repulse Bay", "Southern"),
    "北角": ("North Point", "Eastern"),
    "柴灣": ("Chai Wan", "Eastern"),
    "鰂魚湧": ("Quarry Bay", "Eastern"),
    "筲箕灣": ("Shau Kei Wan", "Eastern"),
    "西營盤及上環": ("Sai Ying Pun & Sheung Wan", "Central & Western"),
    "西營盤": ("Sai Ying Pun", "Central & Western"),
    "西半山": ("Mid-Levels West", "Central & Western"),
    "堅尼地城及摩星嶺": ("Kennedy Town & Mount Davis", "Central & Western"),
    "山頂": ("The Peak", "Central & Western"),
    "灣仔": ("Wan Chai", "Wan Chai"),
    "銅鑼灣": ("Causeway Bay", "Wan Chai"),
    "黃泥湧": ("Wong Nai Chung", "Wan Chai"),
    "渣甸山及黃泥湧峽": ("Jardine's Lookout & Wong Nai Chung Gap", "Wan Chai"),
    "東半山": ("Mid-Levels East", "Wan Chai"),
    # ---- Kowloon ----
    "啟德 - 跑道區": ("Kai Tak - Runway", "Kowloon City"),
    "啟德": ("Kai Tak", "Kowloon City"),
    "何文田": ("Ho Man Tin", "Kowloon City"),
    "紅磡": ("Hung Hom", "Kowloon City"),
    "馬頭角": ("Ma Tau Kok", "Kowloon City"),
    "九龍城": ("Kowloon City", "Kowloon City"),
    "九龍塘": ("Kowloon Tong", "Kowloon City"),
    "旺角": ("Mong Kok", "Yau Tsim Mong"),
    "油麻地": ("Yau Ma Tei", "Yau Tsim Mong"),
    "西南九龍": ("Southwest Kowloon", "Yau Tsim Mong"),
    "長沙灣": ("Cheung Sha Wan", "Sham Shui Po"),
    "石硤尾": ("Shek Kip Mei", "Sham Shui Po"),
    "茶果嶺、油塘及鯉魚門": ("Cha Kwo Ling, Yau Tong & Lei Yue Mun", "Kwun Tong"),
    "牛頭角及九龍灣": ("Ngau Tau Kok & Kowloon Bay", "Kwun Tong"),
    "觀塘": ("Kwun Tong", "Kwun Tong"),
    "觀塘北部": ("Kwun Tong North", "Kwun Tong"),
    "觀塘南部": ("Kwun Tong South", "Kwun Tong"),
    "慈雲山、鑽石山及新蒲崗": ("Tsz Wan Shan, Diamond Hill & San Po Kong", "Wong Tai Sin"),
    # ---- New Territories ----
    "屯門": ("Tuen Mun", "Tuen Mun"),
    "將軍澳": ("Tseung Kwan O", "Sai Kung"),
    "十四鄉(西貢)": ("Sap Sze Heung (Sai Kung)", "Sai Kung"),
    "白沙灣": ("Pak Sha Wan", "Sai Kung"),
    "元朗": ("Yuen Long", "Yuen Long"),
    "天水圍": ("Tin Shui Wai", "Yuen Long"),
    "錦田南": ("Kam Tin South", "Yuen Long"),
    "洪水橋及廈村": ("Hung Shui Kiu & Ha Tsuen", "Yuen Long"),
    "唐人新村": ("Tong Yan San Tsuen", "Yuen Long"),
    "屏山": ("Ping Shan", "Yuen Long"),
    "大埔": ("Tai Po", "Tai Po"),
    "白石角": ("Pak Shek Kok", "Tai Po"),
    "沙田": ("Sha Tin", "Sha Tin"),
    "粉嶺／上水": ("Fanling / Sheung Shui", "North"),
    "粉嶺": ("Fanling", "North"),
    "荃灣": ("Tsuen Wan", "Tsuen Wan"),
    "青衣": ("Tsing Yi", "Kwai Tsing"),
    "愉景灣": ("Discovery Bay", "Islands"),
    "大嶼山南岸": ("South Lantau", "Islands"),
    "長洲": ("Cheung Chau", "Islands"),
}


def area_en(cn: str) -> str:
    return AREA.get(str(cn), (str(cn), None))[0]


def area_district(cn: str):
    return AREA.get(str(cn), (None, None))[1]
