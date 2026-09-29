function RegressZeroDamage takes nothing returns nothing
    if GetUnitUserData(GetTriggerUnit()) == 9 then
        call BlzSetEventDamage(0.0)
    endif
endfunction
