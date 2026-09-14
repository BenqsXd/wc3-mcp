"""Where each kind of game data lives in CASC (paths relative to a mod layer)."""
from dataclasses import dataclass

RACES = ("Campaign", "Human", "Neutral", "NightElf", "Orc", "Undead")
ABILITY_GROUPS = ("Campaign", "Common", "Human", "Item", "Neutral", "NightElf", "Orc", "Undead")
_ABILITY_PROFILES = (tuple(f"Units/{g}AbilityFunc.txt" for g in ABILITY_GROUPS)
                     + tuple(f"Units/{g}AbilityStrings.txt" for g in ABILITY_GROUPS)
                     + ("Units/AbilitySkin.txt", "Units/AbilitySkinStrings.txt"))


@dataclass(frozen=True)
class ObjectKind:
    meta: str                   # metadata SLK
    slks: dict[str, str]        # metadata 'slk' value -> data SLK path
    id_slk: str                 # the 'slk' value whose table lists object ids
    profiles: tuple[str, ...]   # merged txt files; later files override earlier ones
    use_flags: tuple[str, ...]  # metadata columns of which at least one must be "1"; () = every row applies
    name_keys: tuple[str, ...]  # "profile:<key>" or "slk:<column>", first non-empty wins
    suffix_keys: tuple[str, ...]
    level_column: str | None    # data SLK column holding the level count


OBJECT_KINDS = {
    "unit": ObjectKind(
        "Units/UnitMetaData.slk",
        {"UnitData": "Units/UnitData.slk", "UnitBalance": "Units/UnitBalance.slk", "UnitUI": "Units/unitUI.slk",
         "UnitWeapons": "Units/UnitWeapons.slk", "UnitAbilities": "Units/UnitAbilities.slk"},
        "UnitData",
        tuple(f"Units/{r}UnitFunc.txt" for r in RACES) + tuple(f"Units/{r}UnitStrings.txt" for r in RACES)
        + ("Units/UnitSkin.txt", "Units/UnitSkinStrings.txt", "Units/UnitWeaponsFunc.txt", "Units/UnitWeaponsSkin.txt"),
        ("useUnit", "useHero", "useBuilding"), ("profile:name",), ("profile:editorsuffix",), None),
    "item": ObjectKind(
        "Units/UnitMetaData.slk", {"ItemData": "Units/ItemData.slk"}, "ItemData",
        ("Units/ItemFunc.txt", "Units/ItemStrings.txt", "Units/ItemSkin.txt", "Units/ItemSkinStrings.txt"),
        ("useItem",), ("profile:name",), ("profile:editorsuffix",), None),
    "ability": ObjectKind(
        "Units/AbilityMetaData.slk", {"AbilityData": "Units/AbilityData.slk"}, "AbilityData", _ABILITY_PROFILES,
        (), ("profile:name",), ("profile:editorsuffix",), "levels"),
    "buff": ObjectKind(
        "Units/AbilityBuffMetaData.slk", {"AbilityBuffData": "Units/AbilityBuffData.slk"}, "AbilityBuffData",
        _ABILITY_PROFILES, (), ("profile:editorname", "profile:bufftip"), ("profile:editorsuffix",), None),
    "upgrade": ObjectKind(
        "Units/UpgradeMetaData.slk", {"UpgradeData": "Units/UpgradeData.slk"}, "UpgradeData",
        tuple(f"Units/{r}UpgradeFunc.txt" for r in RACES) + tuple(f"Units/{r}UpgradeStrings.txt" for r in RACES)
        + ("Units/UpgradeSkin.txt", "Units/UpgradeSkinStrings.txt"),
        (), ("profile:name",), ("profile:editorsuffix",), "maxlevel"),
    "destructible": ObjectKind(
        "Units/DestructableMetaData.slk", {"DestructableData": "Units/DestructableData.slk"}, "DestructableData",
        ("Units/DestructableSkin.txt", "Units/DestructableSkinStrings.txt"), (), ("slk:Name",), ("slk:EditorSuffix",),
        None),
    "doodad": ObjectKind(
        "Doodads/DoodadMetaData.slk", {"DoodadData": "Doodads/Doodads.slk"}, "DoodadData",
        ("Doodads/DoodadSkins.txt",), (), ("slk:Name",), (), None),
}


@dataclass(frozen=True)
class RowKind:
    slks: tuple[str, ...]
    name_column: str | None


ROW_KINDS = {
    "tile": RowKind(("TerrainArt/Terrain.slk",), "name"),
    "cliff": RowKind(("TerrainArt/CliffTypes.slk",), "name"),
    "water": RowKind(("TerrainArt/Water.slk",), None),
    "sound": RowKind(tuple(f"UI/SoundInfo/{n}.slk" for n in (
        "AbilitySounds", "AmbienceSounds", "AmbientMusic", "AnimSounds", "CinematicSounds", "DialogSounds",
        "EnvironmentSounds", "Music", "UISounds", "UnitAckSounds", "UnitCombatSounds")), None),
}

# kind -> (allowed extensions, required lower-case path substring)
PATH_KINDS = {
    "model": ((".mdx", ".mdl"), ""),
    "icon": ((".blp", ".dds"), "buttons"),
    "file": ((), ""),
}
