You are reading ONE screenshot of a chat conversation (WhatsApp, iMessage, SMS, Instagram, a rental
platform inbox, or similar) for a service that helps students avoid rental scams.

Transcribe every message bubble you can see, top to bottom, exactly as written. Do not correct spelling,
do not translate, do not summarise, do not guess hidden or cut-off text. Keep emojis. Write "[photo]",
"[voice note]", "[link: <visible text>]" or "[document: <name>]" for attachments.

For each bubble give:
- side: "right" for bubbles on the right (usually green or blue: sent by the phone's owner), "left" for
  bubbles on the left (received), "unknown" if you can't tell;
- name: the sender's name only if it is shown on or above the bubble (group chats), else null;
- time: the time or date exactly as shown next to it, else null;
- text: the exact text.

Skip system lines ("Messages are end-to-end encrypted", "Today", date dividers) unless they contain a
date, in which case use that date for the following messages' time.

Also give: is_chat (false if this is not a chat screenshot at all), app (whatsapp, imessage, sms,
instagram, spareroom, openrent, facebook, email, other), other_party (the name in the chat header, if
shown), unreadable (true if the image is too blurry or cropped to read reliably).

Reply with only a JSON object matching this schema:
{schema}
