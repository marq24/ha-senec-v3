> [!IMPORTANT]
> # The new HA marketplace can have _update_ issues

## CASE 1<br>http status errors
For whatever reason HA is not always able to update. Root cause is, that the request to the updated archive file (zip) here at GitHub will be replied with `http 502/503`.

In the update dialog of HA you just see the message "_check your HA logs_" - but there (in the logs) are no further details. I just can assume this has to do with the migration of HACS into HA core [and that the number of http request that the new marketplace integration can send (per hour) is limited - but I have no details or proof - that's really just my assumption!].

To solve this, you can reconnect HACS/Marketplace with your GitHub account. When you try this you might be surprised (like myself) that in contrast to the official documentation there is **no 'Markeplace'** in the _Devices & Services_ listed in `http(s)://[YOUR-HA]/config/integrations`.

**BUT** you still can open it via [this home-assistant.io redirect-link](https://my.home-assistant.io/redirect/integration?domain=marketplace) (or simply via `http(s)://[YOUR-HA]/config/integrations/integration/marketplace`) and then you can select from the 'inner' 3-dot menu the '_Reconfigure Integration_'.

---

## CASE 2<br>Message: The `xxx` directory belongs to `yyy/zzz`
This can happen for three integrations:
- The `senec` directory belongs to `mchwalisz/home-assistant-senec`
- The `fordpass` directory belongs to `itchannel/fordpass-ha`
- The `bosch_ebike` directory belongs to `Phil-Barker/hass-bosch-ebike`

This only happens if you had previously installed another integration version.

Here is a very short step-by-step instruction (the example is for `fordpass` - but I hope you understand the principal)

### 1. stop HA

### 2. make a backup of the `config/.storage/marketplace.repositories` file

### 3. edit `config/.storage/marketplace.repositories`

### 4. search for the other integration in the file
This is either: `itchannel/fordpass-ha`, `mchwalisz/home-assistant-senec` or `Phil-Barker/hass-bosch-ebike` depending on the integration.

So here in this example, the line you are looking for in the `marketplace.repositories` JSON file for the `fordpass` integration is will look like `"full_name": "itchannel/fordpass-ha",`

### 5. scroll down till the line `"installed": true,`
This is for the current entry in the JSON (`itchannel/fordpass-ha`) - if there is no `"installed": true,` then this is not your current issue! - Here is _an example_ how it **could** look like (for sure some of the id's could be different at your installation):
```JSON
    "309018094": {
      "repository_manifest": {
        "name": "fordpass"
      },
      "full_name": "itchannel/fordpass-ha",
      "authors": [
        "@itchannel"
      ],
      "category": "integration",
      "description": "Fordpass integration for Home Assistant",
      "domain": "fordpass",
      "etag_repository": "W/\"57cb613cf6b51f97069410ed9f47265bc56744c64b49e8f48dd97ff0b38a581f\"",
      "last_updated": "2025-11-07T00:20:46Z",
      "stargazers_count": 391,
      "topics": [
        "assistant",
        "car",
        "fordpass",
        "home"
      ],
      "config_flow": true,
      "default_branch": "master",
      "installed_commit": "fb62c82",
      "installed": true,
      "last_commit": "fb62c82",
      "last_version": "1.68-Release",
      "manifest_name": "FordPass",
      "open_issues": 106,
      "prerelease": "1.80-Beta5",
      "published_tags": [
        "1.68-Release",
        "1.66-Release",
        "1.65-Release",
        "1.64-Release",
        "1.63-Release",
        "1.61-Release",
        "1.60-Release",
        "1.58-Release",
        "1.57-Release",
        "1.56-Release",
        "1.54-Release2",
        "1.53-Release",
        "1.52-Release",
        "1.51-Release",
        "1.50-Release",
        "1.49-Release"
      ],
      "releases": true,
      "version_installed": "1.68-Release",
      "last_fetched": 1794423277.877868
    }
```

### 6. edit: `true` to `false`
So that entry finally look like this `"installed": false,` - so it will look like:
```JSON
    "309018094": {
      "repository_manifest": {
        "name": "fordpass"
      },
      "full_name": "itchannel/fordpass-ha",

      ...

      "installed_commit": "fb62c82",
      "installed": false,
      "last_commit": "fb62c82",

      ...

      "version_installed": "1.68-Release",
      "last_fetched": 1794423277.877868
    }
```

### 7. save the file

### 8. restart HA 