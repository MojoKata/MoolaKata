# S12.14. The welcome and the locked screen

14. **The welcome and the locked screen** (S13.6, S15.4). Both are outside the frame, in the
    card the sign-in screens use.
    1. **The welcome**, while the server has no keyring: every address under `/ui` shows it.
       **Welcome to MoolaKata** says the data will be kept under a master key that is a
       recovery phrase of 12 words, written down by the admin, asked for at every restart and
       recoverable by nobody; **Show my recovery phrase** shows a new phrase (S15.4.4): the 12
       words numbered, with the fingerprint, to write on paper. **I've written them down** asks
       for three of them by number; wrong ones are refused with "check your sheet", and
       **Back** shows the same words again. Right, the key is made and the server unlocked,
       and **Set up the admin account** follows (S10.1.2), then the Dashboard. A reload, or
       another browser, shows a new phrase; only the one confirmed is kept.
    2. **The locked screen**, while the server has a keyring but no key: every address under
       `/ui` shows it: the server has started and holds no key, with a field for the 12 words
       of the recovery phrase and **Unlock**, and a line naming the host command that does the
       same. The field is masked in every supported browser, with the eye button to show it
       (S12.1.3), and turns off the browser's autocorrect, autocapitalize, spellcheck and
       autocomplete, so nothing learns or keeps the words. While a re-encryption runs at the
       unlock (S15.7.2), the screen shows its progress, and gives way to sign-in when it is
       done. A wrong phrase is refused at the field; after the lockout of S13.7.5.1 the screen
       says how long to wait. Once unlocked, the screen gives way to sign-in, or to **Set up
       the admin account** while there are no users (S10.1.2). A page open when the server
       restarts lands on it at its next request, as it lands on sign-in when a session ends
       (S12.6). After **Rotate** or **Re-encrypt now** (S16.13), the page that asked shows
       **MoolaKata is restarting** until the server answers locked, then this screen; a
       server not back within a minute is said to need starting on the host.
