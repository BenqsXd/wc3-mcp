"""Locate local Warcraft III data for corpus tests (read at runtime, never committed)."""
import functools
import os
from pathlib import Path

import pytest

INSTALL = Path(os.environ.get("WC3MCP_INSTALL", r"D:\Warcraft III"))
HAVE_INSTALL = (INSTALL / ".build.info").is_file()
needs_install = pytest.mark.skipif(not HAVE_INSTALL, reason="Warcraft III install not found")


def ladder_maps() -> list[Path]:
    from wc3mcp import config

    root = config.documents() / "Maps" / "Download"
    seen, out = set(), []
    for p in sorted(root.rglob("*.w3x")) if root.is_dir() else []:
        if p.name.lower() not in seen:
            seen.add(p.name.lower())
            out.append(p)
    return out


CASC_SAMPLE_MAPS = (
    "Campaign/Reforged/ROC/Human01.w3x",            # w3i v39, many imports, locale strings
    "Campaign/Classic/ROC/Undead02Interlude.w3m",   # w3i v39
    "Campaign/Classic/TFT/HumanX01.w3x",            # w3i v39 players with flag 0x40
    "Campaign/Reforged/ROC/Prologue01.w3x",         # w3i v39
    "Maps/Scenario/(4)WarChasers.w3m",              # w3i v33, JASS
    "Maps/FrozenThrone/Community/2023Season2/(8)RoyalGardens_S2_v1.2.w3x",  # w3i v33, Lua
    "Maps/FrozenThrone/(10)RagingStream.w3x",       # w3i v31
    "Campaign/Classic/TFT/HumanX04Interlude.w3x",   # w3i v31, object data v2
    "Campaign/Reforged/ROC/Human05.w3x",            # wtg with deleted-id counters (comments, kind 128)
)


@functools.cache
def _storage():
    from wc3mcp.casc.storage import open_storage

    return open_storage(INSTALL)


@functools.cache
def _ladder_by_name() -> dict:
    return {p.name: p for p in ladder_maps()}


def sample_map_ids() -> list[str]:
    ids = [f"ladder:{name}" for name in _ladder_by_name()]
    if HAVE_INSTALL:
        ids += [f"casc:{m}" for m in CASC_SAMPLE_MAPS]
    return ids


@functools.cache
def open_sample(map_id: str):
    from wc3mcp.mpq.reader import Archive

    kind, name = map_id.split(":", 1)
    if kind == "casc":
        return Archive(_storage().read("War3.w3mod:" + name))
    return Archive.open(_ladder_by_name()[name])


# game models holding every rare MDX chunk and track kind and the versions other than 1800 (from a scan of all 14,984)
RARE_MODELS = (
    "War3.w3mod:Abilities/Spells/Other/Tornado/TornadoSpinner.mdx",  # ATCH
    "War3.w3mod:UI/Feedback/Resources/resources.mdx",  # BONE GEOS
    "War3.w3mod:_DE.w3mod:Doodads/Barrens/Props/TaurenTotem/TaurenTotem2.mdx",  # BPOS
    "War3.w3mod:Objects/CinematicCameras/CameraCloseUpLow.mdx",  # CAMS KCRL
    "War3.w3mod:_DE.w3mod:Doodads/Ashenvale/Plants/AshenCanopyTree/AshenCanopyTree3D.mdx",  # CLID
    "War3.w3mod:Cinematics/A0M1C020_ArthasArrives/vfx/Arthas_petal.mdx",  # CORN
    "War3.w3mod:_DE.w3mod:Doodads/Undercity/Structures/NaxxStair/NaxxStair3.mdx",  # DILG
    "War3.w3mod:_DE.w3mod:Buildings/Undead/TempleOfTheDamned/TempleOfTheDamnedDeath.mdx",  # ELAF IDUF PTSF
    "War3.w3mod:Abilities/Spells/Undead/Impale/ImpaleCaster.mdx",  # EVTS PIVT
    "War3.w3mod:_DE.w3mod:Doodads/Cinematic/UtherTome/UtherTome.mdx",  # FAFX
    "War3.w3mod:UI/Feedback/ManaBarConsole/ManaBarConsole.mdx",  # GEOA
    "War3.w3mod:Environment/DNC/DNCDungeon/DNCDungeonTerrain/DNCDungeonTerrain.mdx",  # GLBS KGRT
    "War3.w3mod:Objects/Spawnmodels/Other/HumanBloodCinematicEffect/HumanBloodCinematicEffect.mdx",  # HELP KP2S
    "War3.w3mod:Objects/InventoryItems/PotofGold/PotofGold.mdx",  # KATV
    "War3.w3mod:Objects/CinematicCameras/CameraZoomInLow.mdx",  # KCTR
    "War3.w3mod:Doodads/BlackCitadel/Props/RuneArt/RuneArt0.mdx",  # KGAC
    "War3.w3mod:Doodads/Cinematic/RunesOfGuldan/RunesOfGuldan0.mdx",  # KGAO
    "War3.w3mod:_DE.w3mod:UI/Feedback/CommandButton/UICommandButtonHighlight.mdx",  # KGSC
    "War3.w3mod:Abilities/Spells/Items/AIfb/AIfbSpecialArt.mdx",  # KGTR
    "War3.w3mod:_HD.w3mod:Environment/DNC/DNCLordaeron/DNCLordaeronUnit/DNCLordaeronUnit.mdx",  # KLAC
    "War3.w3mod:Environment/DNC/DNCLordaeron/DNCLordaeronTarget/DNCLordaeronTarget.mdx",  # KLAI KLBI
    "War3.w3mod:Abilities/Weapons/FrostWyrmMissile/FrostWyrmMissile.mdx",  # KLAV
    "War3.w3mod:Environment/DNC/DNCDungeon/DNCDungeonUnit/DNCDungeonUnit.mdx",  # KLBC
    "War3.w3mod:UI/Feedback/Target/Target.mdx",  # KMTA
    "War3.w3mod:_DE.w3mod:Doodads/Cinematic/GlowingRunes/GlowingRunes0.mdx",  # KMTE
    "War3.w3mod:Abilities/Spells/NightElf/MoonWell/MoonWellTarget.mdx",  # KMTF KTAR
    "War3.w3mod:Abilities/Spells/NightElf/MoonWell/MoonWellCasterArt.mdx",  # KP2E
    "War3.w3mod:Abilities/Spells/Human/Polymorph/PolyMorphDoneGround.mdx",  # KP2L
    "War3.w3mod:Abilities/Weapons/SteamMissile/SteamMissile.mdx",  # KP2N KP2W
    "War3.w3mod:Abilities/Spells/Undead/DarkRitual/DarkRitualCaster.mdx",  # KP2V PRE2
    "War3.w3mod:Abilities/Weapons/PoisonSting/PoisonStingMissile.mdx",  # KPEV PREM
    "War3.w3mod:_DE.w3mod:Units/NightElf/Wisp/Wisp.mdx",  # KPPA
    "War3.w3mod:_DE.w3mod:Abilities/Spells/Orc/LiquidFire/Liquidfire.mdx",  # KPPE
    "War3.w3mod:Cinematics/A0M4C010_ShutUp/A0M4C010_ShutUp.mdx",  # KPPL
    "War3.w3mod:_DE.w3mod:Abilities/Spells/Other/Thrusters/ThrusterOrange.mdx",  # KPPS
    "War3.w3mod:Cinematics/A3MiC010_AllIsQuiet/vfx/Nax_LaserCast.mdx",  # KPPV
    "War3.w3mod:Abilities/Spells/NightElf/MoonGlaive/MoonGlaiveCaster.mdx",  # KRAL
    "War3.w3mod:Abilities/Spells/Human/Resurrect/Resurrecttarget.mdx",  # KRHA KRHB
    "War3.w3mod:_DE.w3mod:Abilities/Spells/NightElf/TargetArtLumber/TargetArtLumber.mdx",  # KRVS
    "War3.w3mod:Abilities/Spells/Human/Defend/DefendCaster.mdx",  # KTAS
    "War3.w3mod:UI/Feedback/CheckpointPopup/CheckpointPopup.mdx",  # KTAT TXAN
    "War3.w3mod:_HD.w3mod:Cutscenes/Human_06_Intro/culling_intro_130.mdx",  # KTTR
    "War3.w3mod:_DE.w3mod:Doodads/Cinematic/OmniLight/OmniLightOrange.mdx",  # LITE
    "War3.w3mod:_DE.w3mod:Doodads/Cityscape/Structures/CityBuildings/CityBuildings.mdx",  # MODL
    "War3.w3mod:_DE.w3mod:Abilities/Spells/NightElf/SpiritOfVengeance/SpiritOfVengeanceOrbs1.mdx",  # MTLS RIBB TEXS
    "War3.w3mod:_DE.w3mod:Doodads/Ashenvale/Rocks/AshenRock/AshenRock0.mdx",  # SEQS
    "War3.w3mod:Cinematics/A0M4C010_ShutUp/environment/dark.mdx",  # v1600
    "War3.w3mod:Cinematics/A0M1C020_ArthasArrives/environment/A0M1C020_ArthasArrives_DNC.mdx",  # v1700
)


def sample_models(storage, others: int, seed: int = 5) -> list[str]:
    """RARE_MODELS still in the install plus `others` models picked with a fixed seed"""
    import random

    names = sorted(n for n in storage.list("") if n.lower().endswith(".mdx"))
    present = set(names)
    return [n for n in RARE_MODELS if n in present] + random.Random(seed).sample(names, others)
