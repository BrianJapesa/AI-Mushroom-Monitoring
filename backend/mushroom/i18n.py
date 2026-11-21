"""Short alert phrases; Swahili strings need a native-speaker review."""

# NEEDS NATIVE-SPEAKER REVIEW
MESSAGES = {
    "en": {
        "subject": "{level}: Mushroom room alert",
        "action": "Check the room sensor and make the needed ventilation or misting adjustment.",
        "offline_action": "Check sensor power and the room's Wi-Fi connection.",
        "digest_subject": "Daily mushroom-monitor alert summary",
        "sms": "{farm}: {level} {kind} at {location}. {message} Open {url}",
    },
    "sw": {
        "subject": "{level}: Tahadhari ya chumba cha uyoga",
        "action": "Kagua kifaa cha kupima na rekebisha hewa au unyevunyevu inapohitajika.",
        "offline_action": "Kagua umeme wa kifaa na muunganisho wa Wi-Fi.",
        "digest_subject": "Muhtasari wa kila siku wa tahadhari za uyoga",
        "sms": "{farm}: {level} {kind} {location}. {message} Fungua {url}",
    },
}
