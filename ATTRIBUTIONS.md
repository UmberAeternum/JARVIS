# Third-Party Attributions

UMBRA is built on open-source software. The authors and licenses of the
direct dependencies are listed below; each remains the property of its
authors under its own license.

## Desktop assistant (Python)

| Package | License |
|---|---|
| openai | Apache-2.0 |
| rich | MIT |
| psutil | BSD-3-Clause |
| ddgs | MIT |
| cryptography (PRO license validation) | Apache-2.0 / BSD-3-Clause |
| pillow (vision extra) | MIT-CMU |
| mss (vision extra) | MIT |
| sounddevice (voice extra) | MIT |
| numpy (voice extra) | BSD-3-Clause |
| pyttsx3 (voice extra) | MPL-2.0 |
| vosk (voice extra) | Apache-2.0 |
| pyautogui (control extra) | BSD-3-Clause |
| keyring (secure extra) | MIT |

## Android launcher (Kotlin)

| Library | License |
|---|---|
| Jetpack Compose | Apache-2.0 |
| OkHttp | Apache-2.0 |
| AndroidX Security Crypto (EncryptedSharedPreferences) | Apache-2.0 |

## Runtime components used on-device

- Android SpeechRecognizer and TextToSpeech: provided by the platform vendor.
- Vosk speech model (small-en-us): downloaded at first use from alphacephei.com
  under the Apache-2.0 license. The model runs entirely on the device.
- MediaPipe Hands tracker (phase 13 gestures): vendored on the user's explicit
  command (`jarvis gestures vendor`) from the @mediapipe/hands npm distribution
  (jsdelivr), Apache-2.0 License, Copyright 2023 The MediaPipe Authors. The
  bundle runs entirely inside the browser; camera frames never leave the device
  and only normalized landmark coordinates reach the local HUD API.

## Trademarks

UMBRA and its logo are marks of the publisher. All other product names and
logos are trademarks of their respective owners. This product is not
affiliated with, endorsed by, or connected to any other software or media
property sharing a similar name.
