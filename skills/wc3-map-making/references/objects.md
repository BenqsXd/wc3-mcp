# Map info, object data and order strings

## Map info

- `info_edit` `set` of a whole list (`forces`, `players`) replaces it, and every element must be complete, including `unknown_flag_bits`. Read the shape from `info_get` first. A path can reach one field inside an element instead (`forces[0].name`, `forces[0].flags.allied`).
- Accepted in one batch: `description`, `players_recommended`, `flags.use_custom_forces`, `flags.fixed_player_settings_for_custom_forces`, `flags.melee_map`, `flags.use_terrain_fog`, `forces[0].flags.allied_victory` / `share_vision`, a whole `fog` object (`style`, `start_z`, `end_z`, `density`, `color`), `water_tint`, `loading_screen.title` / `subtitle` / `text`.
- Art fields (for example an ability's research icon `arar`) live in the skin files (`war3mapSkin.w3a`), so `map_save merge_external=true` keeps them with the working copy's changes.

## objdata_edit

- Icons and models: `data_search kind=icon` / `kind=model` take globs (`*BTN*Scroll*`, `*MassTeleport*`, no layer prefix needed) and return storage paths (`War3.w3mod:ReplaceableTextures/CommandButtons/BTNSkillz.dds`); in object data write `ReplaceableTextures\CommandButtons\BTNSkillz.blp`, which loads in the game. `kind=file` results carry that form as `ref`.

- `create` takes an explicit `id` (`"h000"`) or allocates one like the editor. `set` also works on stock ids (`hgtw`), which makes modified standard objects. `base` may be one of the map's custom objects (`{"op": "create", "id": "u001", "base": "u000", "set": {...}}`): the copy gets its stock base and all its modifications, then `set`.
- Fields take raw codes, field names or display names. Per-level ability fields take level keys: `{"aran": {"1": 620}}`, `{"acdn": {"1": 20}}`. Other fields take plain values (`"aher": 0`, `"alev": 1`); Channel's animation names `aani` has no levels. A unit's `uabi`, `uhab`, `usei` and an item's `iabi` are comma-separated id strings (`"A003,A004"`).
- Field values are range-checked against the editor metadata (`ussc must be between 0.1 and 20`, `ulev must be between 1 and 100`), which catches bad values before any save.
- `objdata_get` sizes `levels` and per-level lists by the map's own `alev` (abilities) or `glvl` (upgrades); values stored for levels beyond it are listed under `unused_levels` and do not exist in the game.
- **Raising `alev` past the base ability's own level count** leaves the base with nothing to read in the new ranks, so `objdata_edit` repeats the last value of every per-level field into them, as the World Editor does, and lists what it filled in under `extended_levels`. Author the ranks that should differ; the rest already carry the rank-3 (or whatever the base ends at) value.
- Values may be given as numeric strings (`"0"`, `"600.5"`), which is what `data_get` hands back, and `null` clears a field or one level of it (`{"aubx": null}`), leaving the base object's own value.
- `objdata_get` checks the model the object really uses: when the map changes `umdl` (or `dfil`/`bfil` and the variation count), `model.files` and `model.missing` follow the map's value (`source: "map"`), and imported models count as present.
- Art fields accept empty strings: `ushb` (building shadow) and `uubs` (ground texture) set to `""` remove them.
- `data_get` and `objdata_get` take a **list of ids** and answer compactly (raw code -> value); `verbose=true` brings back each field's name, category and type.

## Copies keep what their base has

`map_validate` warns about all three of these: checks `inherited_builds`, `locked_ability` and `command_card`.

- A copy of `ewsp` (Wisp) with a new `uabi` still has the Wisp's build list (`ubui` `etol,emow,...`): set `ubui` to `""` on workers that must not build.
- A copy of `otau` keeps `Awar` (Pulverize), whose `areq` is the research `Rows`; a hero copy of a Warden keeps `Ault`, which needs `Reuv`. Without that research the ability is unusable. `SetPlayerTechResearched(Player(i), 'Reuv', 1)` at map start clears both the problem and the warning.
- `ARal` (Rally) sits at button position (3, 1) and Cancel at (3, 2) on buildings that train units, so a trained unit or research on the same slot hides one of them.
- A builder needs no build ability: a copy of `uaco` (Acolyte) with `uabi` `"Avul"` and a `ubui` list of custom buildings shows a Build command.
- The neutral tavern heroes `Nbst`, `Nfir` and `Nngs` carry `ureq` `"TALT"`, which must be cleared or they cannot be bought.

## Units, buildings and shops

- Unit fields for custom buildings: `upat` pathing texture, `usca` model scale, `umpm`/`umpi`/`umpr` mana maximum/initial/regeneration, `ufma` food produced, `ubpx`/`ubpy` button position, `uupt` upgrades to, `upgr` upgrades used, `ures` researches, `utra` units trained. `umvt` `"fly"` with `umvh` makes a flying unit. Setting `ureq` to `""` removes tech requirements.
- Pathing textures come in many sizes under `PathTextures\` (`4x4SimpleSolid`, `8x8Simple`, `12x12Simple`, `16x16Simple`, ...; one cell is 32 world units). Stock sizes: Barracks and Beastiary `12x12Simple`, Castle `16x16Simple`, Guard and Cannon Tower `4x4SimpleSolid`.
- A building **sells** units through `useu` (Units Sold), not `utra`: a copy of `ntav` (Tavern) with `useu` set to four custom hero ids and its stock `uabi` (`Ane2,Avul,Aawa`) kept selling them.
- The stock fields live on the **sold unit**, not on the shop: `usma` stock maximum, `usit` initial stock, `usst` start delay (seconds), `usrg` replenish interval. `usma` 1, `usit` 1, `usst` 0, `usrg` 999 makes a hero available from the first second and not again. At runtime `AddUnitToStock(shop, id, 1, 1)` and `RemoveUnitFromStock(shop, id)` restock and empty them.
- Free heroes: `ugol` 0, `ulum` 0, `ufoo` 0 on the hero copy.
- A shop sells the items in its `usei`: a copy of `nmgv` (Magic Vault) with `uabi` `"Aneu,Avul,Apit"` sold items to a hero, and `IssueNeutralImmediateOrderById` bought one and charged the gold.
- A hero's `uhab` takes at most 5 abilities (`maxVal` 5): with 11, `SelectHeroSkill` learned the 1st and 4th but not the 9th.

## Gameplay constants

- `constants_get` / `constants_edit` read and write the Gameplay Constants (`war3mapMisc.txt` over the game's `Units/MiscGame.txt` and `Units/MiscData.txt`); an editor save keeps the file. A misspelt key is refused, and `map_validate` warns (check `constant`) about one already in a map.
- A level cap of 25: `{"MaxHeroLevel": 25, "MaxUnitLevel": 25, "HeroAbilityLevelSkip": 1}`. Verified in the game: `AddHeroXP(h, 40000, false)` took a fresh hero to level 25 and `SetHeroLevel(h, 25, false)` gave exactly 25 skill points.
- The experience curve is `NeedHeroXP` 200 with `NeedHeroXPFormulaA/B/C` (1/100/0), which gives 200, 500, 900, 1400, 2000, ... `HeroFactorXP` `80,70,60,50,0` is why a hero gets no creep experience from level 5 on.
- Attributes are worth what these say: `StrHitPointBonus` 25, `IntManaBonus` 15, `StrAttackBonus` 1, `AgiDefenseBase` -2 with `AgiDefenseBonus` 0.30, `AgiAttackSpeedBonus` 0.02. `balance_report kind="unit"` computes a hero's real life, mana, armour and damage from them at level 1 and at the cap.

## Custom heroes

- **Hero stats do not live in the unit fields.** Every stock hero has `uhpm` 100, `umpm` 0, `ua1b` 0, `ua1d` 2, `umpr` 0.01: life comes from strength, mana from intelligence, damage from the primary attribute (`upra`). Tune `ustr`/`ustp`, `uagi`/`uagp`, `uint`/`uinp`, `ua1s`, `ua1c`, `udef`, `umvs`. Measured at level 25: strength 104 gave 2700 life, intelligence 96 gave 1440 mana.
- **Rank gating:** `alev` ranks, `arlv` the hero level the first rank needs, `alsk` the levels between ranks (0 falls back to `HeroAbilityLevelSkip`). Three basics with `alev` 7 / `arlv` 1 / `alsk` 1 and one ultimate with `alev` 4 / `arlv` 6 / `alsk` 4 let a level-25 hero spend all 25 points (3 x 7 + 4 = 25).
- **Hero glow on a creep model:** a unit built from a hero base but wearing a creep model has no glow disc. Copy `Asph` (Sphere) with `atat` = `Abilities\Spells\Other\HeroGlow\HeroGlow.mdl`, `atac` 1, `ata0` `origin`, icons, tooltips and missile art cleared, and put that copy in the unit's **`uabi`** (not `uhab`): `uabi` = `"AInv,A099"`. One copy serves every hero; the Blood Mage (`Hblm`, `uabi` `AInv,Asph`) is the stock precedent.
- **Ability bases that need repairs when copied into a hero ability:** `aher` is 0 on `Afae`, `Aslo`, `Ablo`, `ACcy` and `ACrj` - set it to 1. `Ablo` also carries `areq` `Rost` with `arqa` 2, which greys the button out: clear both. Autocast bases (`Afae`, `Aslo`, `Ablo`, `ANfa`) keep `aoro`/`aorf`/`auar`; clearing those three makes a plain unit-target ability. Prefer the variant without a tech requirement: `ACcy` over `Acyc`, `ACrj` over `Arej`.
- **Summon abilities** take the unit id per rank (Feral Spirit `Osf1`, Serpent Ward and Water Elemental `Hwe1`/`Hwe2`, Force of Nature `Efnu`, Tornado `Ntou`, Locust Swarm `Ulsu`), and Reforged wants `ausk` (Unit Skin List) set to the same ids. Force of Nature (`AEfn`) eats trees, so it opens holes in a tree wall that is the map's terrain - Serpent Ward does not.
- **A creep model carries its stock attack style:** every forest troll (`nftr`, `nftb`, `nftk`, `nftt`) is a ranged axe thrower, so a melee passive such as Cleaving Attack needs a melee model (`nfra`, `nsqe`, `nmyr`, `nstl`, `nomg`, `nmrm`; `ngna`, `nhrw`, `nssp` are ranged). `usnd` carries the voice and death cry (`Murloc`, `Wendigo`, `Furbolg`, `GnollArcher`, `NagaMyrmidon`, `Satyr`, `Harpy`, `Spider`, `Ogre`).
- An editor save moves names and tooltips into `war3map.wts` as `TRIGSTR_` references and splits art fields into `war3mapSkin.w3a` / `war3mapSkin.w3u`; ids and values survive (`map_save merge_external=true`).

## Items and abilities

- Item fields: `iabi` abilities, `igol` gold cost, `iico` icon, `ifil` model, `icla` class, `ilev` level, `isel` sold by merchants, `ipaw` sellable, `iprn` random choice, `isto` stock maximum, `istr` replenish interval, `isst` start delay, `isit` initial stock, `uhot` hotkey, `utip` / `utub` tooltips, `ides` description. A custom item inherits its base's hotkey (`rst1`: `S`).
- Stock item abilities and their bonus fields (all per level): `AIx5` all stats (`Iagi`, `Iint`, `Istr`, `Ihid`), `AItc` damage (`Iatt`), `AIsx` attack speed (`Isx1`, a fraction), `AIlf` max life (`Ilif`), `Arel` life regeneration (`Ihpr`), `AImb` max mana (`Iman`), `AIrm` mana regeneration (`Imrp`), `AId3` armor (`Idef`), `AIcs` critical strike (`Ocr1` chance, `Ocr2` multiplier). Basic items: `rst1`, `rag1`, `rin1` (+3 stat), `ratc` Claws +12, `gcel` Gloves of Haste, `rde2` Ring of Protection +3, `prvt` Periapt, `rlif` Ring of Regeneration, `penr` Pendant of Energy, `rwiz` Sobi Mask.
- Channel (`ANcl`): `Ncl1` follow-through time, `Ncl2` target type (0 none, 1 unit, 2 point, 3 unit or point), `Ncl3` option bits (1 visible, 2 targeting image, 4 physical, 8 universal, 16 unique cast), `Ncl4` art duration, `Ncl5` disable other abilities, `Ncl6` base order id. Several Channel copies on one unit need distinct `Ncl6` orders (`acidbomb`, `howlofterror`, `avengerform`, `doom`); with `Ncl1` 0 and `Ncl5` 0 each is cast by its own order string.
- A hidden, learnable, effect-free hero ability: copy `Aamk` (Attribute Bonus) with `Iagi`/`Iint`/`Istr` 0 and `Ihid` 1 on every level. It shows in the learn menu with its `arar` icon and `aret`/`arut` tooltips and has no command-card button.
- True Sight abilities (`Adtg`, `Atru`, `ANtr`, `Agyv`, `Adts`, `Adt1`) detect within `aran` (Cast Range), not `aare`.
- `Apiv` (Permanent Invisibility) fades in over `adur`/`ahdu`, 2 seconds by default. With both set to 0, a unit given the ability turns invisible at once.

## Order strings

A script that orders a unit to cast needs the order string, and **the ability data and the World Editor disagree for about 15 of the 832 abilities**. Only one of the two works per ability, and neither side is always right.

- `data_get kind=ability` returns an `orders` block: `data` (the ability's own `aord` / `aoro` / `aorf`), `editor` (the editor's presets for it, each with the targeting kind: `immediate`, `point`, `unit`, `item`, `destructible`) and `disagree: true` when they differ. Some abilities name no order of their own and only the editor does (`AHdr` Siphon Mana: `drain`; `ANfa` Frost Arrows: `coldarrowstarg`).
- Known disagreements, checked in the game (`orders.game` in `data_get`): `ANlm` Summon Lava Spawn takes `lavamonster` (editor), not `slimemonster` (data); `AUin` Inferno takes `dreadlordinferno` (editor), not `inferno`; `AHpx` Phoenix takes `summonphoenix` (data), not `phoenix`.
- `IssueImmediateOrder`, `IssuePointOrder` and `IssueTargetOrder` return `false` for a string the unit cannot use, and a rejected order leaves `GetUnitCurrentOrder` at 0, so a script can try one string, check the result and fall back to the other.
- `map_validate` warns (check `order_string`) when a script issues an order that is one of these disagreeing data orders, or one that matches no ability order and no editor preset at all.

## Reviewing a batch

`objdata_diff` says what the map's object data of one kind changed against the map file on disk (`against="source"`) or against a snapshot (`map_snapshot action=create` first): objects added or deleted, and per object every field whose value differs, with the value before and after. Read it before `map_save`, or after a World Editor session to see what the editor did.

## What an object is worth

`balance_report` computes it from the fields instead of guessing: for a unit the damage per second of every enabled
attack ((base + dice * (sides + 1) / 2) / cooldown), the effective life its armour buys (life / (1 - 0.06 * armour /
(1 + 0.06 * armour))), and both per 100 gold; for an item the bonuses its abilities give per 100 gold; for an ability
the per-level curve with damage per mana and per second of cooldown. Every row carries the stock objects closest in
price and food, and a flag when a ratio is far outside theirs - which is how a tier-1 unit that out-damages a Knight
for half the gold gets caught without a game run. The result names the formulas and the fields it read.

A unit with `udty` `hero` is read as a hero instead: life, mana, armour, attack bonus and damage per second computed
from `ustr`/`uagi`/`uint` and the gameplay constants, at level 1 and at `MaxHeroLevel`, under `hero`, and compared
with the stock heroes. Reading a hero's plain fields says life 100 and damage 2 for every hero there is.

## The string table

`strings_get` reads war3map.wts: every name, tooltip and quest text the map shows, with `used_by` saying which files
point at each entry and marking the ones nothing refers to any more. `strings_edit` sets, adds and removes entries,
imports a translated table in one go, and `replace` renames one thing everywhere the map shows it. Object data, map
info and GUI triggers all point at these entries, so they follow; the map script keeps its own copy, so `map_save`
(or `script_build`) has to regenerate it afterwards.
