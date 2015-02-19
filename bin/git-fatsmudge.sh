#!/bin/sh

IFS=''
read -n 12 PREFIX


if [[ '#$# git-fat ' == "$PREFIX" ]]; then
    read -n 40 HASH
    
    if [ -e .git/fat/objects/$HASH ]; then
        cat .git/fat/objects/$HASH
    else
        printf "${PREFIX}"
        printf "${HASH}"
        cat        
    fi
else
    printf "${PREFIX}"
    cat
fi

# HASH=`egrep -o '[0-9a-f]{40}'`

# cat .git/fat/objects/$HASH



