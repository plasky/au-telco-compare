# Bill Hero feed snapshot

Copies of Bill Hero's open data feeds (https://billhero.com.au/data/broadband and
https://billhero.com.au/data/mobile), licensed CC-BY-4.0. Data via Bill Hero (billhero.com.au).

Bill Hero challenges automated clients, so the nightly refresh can't fetch these itself. The
Bill Hero adapter falls back to this snapshot while it is under 8 days old (`snapshot.json`
says when it was taken). To refresh it, download both feeds in a browser and run:

    tools/import-billhero.sh ~/Downloads/broadband.json ~/Downloads/mobile.json
