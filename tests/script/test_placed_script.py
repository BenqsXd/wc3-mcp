from wc3mcp.script import placed


def test_random_item_spelling_follows_the_scripts_editor():
    current = "call RandomDistAddItem( ChooseRandomItemExWithFilter( ITEM_TYPE_POWERUP, 1, EQUIPMENT_TYPE_ANY, ITEMTAG_TYPE_ANY), 100 )"
    assert placed.random_item_style(current) == placed.random_item_style("no random items") == "filter"
    assert placed.random_item_style("ChooseRandomItemEx( ITEM_TYPE_ANY, 2 )") == "any"
    assert placed.random_item_style("ChooseRandomItem( 4 ) ChooseRandomItemEx( ITEM_TYPE_CHARGED, 1 )") == "plain"
    assert placed._item_expr(b"YYI1", "filter") == \
        "ChooseRandomItemExWithFilter( ITEM_TYPE_ANY, 1, EQUIPMENT_TYPE_ANY, ITEMTAG_TYPE_ANY)"
    assert placed._item_expr(b"YkI3", "filter") == \
        "ChooseRandomItemExWithFilter( ITEM_TYPE_POWERUP, 3, EQUIPMENT_TYPE_ANY, ITEMTAG_TYPE_ANY)"
    assert placed._item_expr(b"YYI1", "plain") == "ChooseRandomItem( 1 )"
    assert placed._item_expr(b"YYI1", "any") == placed._item_expr(b"YYI1", "any") == "ChooseRandomItemEx( ITEM_TYPE_ANY, 1 )"
    assert placed._item_expr(b"YiI2", "plain") == "ChooseRandomItemEx( ITEM_TYPE_PERMANENT, 2 )"
    assert placed._item_expr(b"ratc", "filter") == "'ratc'" and placed._item_expr(b"\0\0\0\0", "any") == "-1"


def test_drop_chances_below_100_add_a_no_item_entry():
    text = placed._drop_function("Unit000001_DropItems", [[(b"ratc", 60)], []], "filter")
    assert "call RandomDistAddItem( 'ratc', 60 )\n        call RandomDistAddItem( -1, 40 )" in text
    assert "// Item set 1\n        call RandomDistReset(  )\n        call RandomDistAddItem( -1, 100 )" in text
