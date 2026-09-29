function RegressFlagHandler takes nothing returns nothing
    if BlzGetEventIsAttack() then
        call SetUnitUserData(GetTriggerUnit(), 1)
    else
        call SetUnitUserData(GetTriggerUnit(), 2)
    endif
endfunction
