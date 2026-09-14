from wc3mcp.gamedata.profile import parse_profile, split_list, unquote

TEXT = ('﻿// comment\r\n[AHbz]\t\r\nName=Blizzard\r\nTip=Blizzard - [Level 1],Blizzard - [Level 2]\r\n'
        'Ubertip="Calls down <AHbz,DataA1> waves.","Calls down <AHbz,DataA2> waves."\r\n'
        'modelScale:hd=1\r\n\r\n[hfoo]\r\nName=Footman\r\n').encode("utf-8")


def test_parse_sections_keys_and_comments():
    p = parse_profile(TEXT)
    assert set(p) == {"AHbz", "hfoo"}
    assert p["AHbz"]["name"] == "Blizzard"
    assert p["AHbz"]["modelscale:hd"] == "1"


def test_later_files_override_and_merge():
    p = parse_profile(TEXT)
    parse_profile(b"[hfoo]\nName=Footman2\nHotkey=F\n", into=p)
    assert p["hfoo"] == {"name": "Footman2", "hotkey": "F"}
    assert p["AHbz"]["name"] == "Blizzard"


def test_split_list_honors_quotes():
    p = parse_profile(TEXT)
    assert split_list(p["AHbz"]["tip"]) == ["Blizzard - [Level 1]", "Blizzard - [Level 2]"]
    assert split_list(p["AHbz"]["ubertip"]) == ["Calls down <AHbz,DataA1> waves.", "Calls down <AHbz,DataA2> waves."]
    assert split_list("") == [""]


def test_unquote():
    assert unquote('"a,b"') == "a,b" and unquote("plain") == "plain" and unquote('"') == '"'
