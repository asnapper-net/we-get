#!/bin/bash
set -e
keys=($(jq -r 'keys | .[]' $EP_FILE))
for key in "${keys[@]}"; do
    echo "--- processing $key"

    if [ "$(jq --arg key "$key" -r '. | .[$key] | .torrent' $EP_FILE)" == "null" ]; then
        echo "--- found no existing torrent info for $key"
        
        # build we get command
        cmd=$(jq --arg key $key -r '. | .[$key] | @sh "we-get --search=\(.show) --filter \(.season_padded+.episode_padded) --quality=1080p -n 10 --json"' $EP_FILE)

        id=$(jq --arg key $key -r '. | .[$key] | .season_padded+.episode_padded' $EP_FILE)
        show=$(jq --arg key $key -r '. | .[$key] | .show_normalized' $EP_FILE)
        echo "--- $show episode id is $id for $key"

        # run we get command
        echo "--- executing command $cmd"
        torrent=$(eval "$cmd" | jq --arg cmd "$cmd" --arg id "$id" --arg show "$show" '([keys | .[] |select(contains($id|tostring) and contains($show|tostring))][0]) as $key | .[$key] | .release=$key | .cmd=$cmd' 2>/dev/null || echo null)

        if [ $? -eq 0 ]; then
            echo "--- got some search results for $key"
            release=$(jq -r -n --argjson torrent "$torrent" '$torrent.release')
            tmp=$(mktemp)
            jq -r --arg key "$key" --arg torrent "$torrent" '. | .[$key].torrent = ($torrent|fromjson)' $EP_FILE > $tmp
            [ $? -eq 0 ] && mv $tmp $EP_FILE
        else
            echo "--- nothing usable found for $key"
        fi

    else
        echo "--- already got torrent info for $key"
    fi
done
