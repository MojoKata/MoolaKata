# S12.12. Exact numbers in the browser

12. **Exact numbers in the browser.** Every amount, quantity, price and ratio the API sends
    arrives as an exact decimal (S13.8.2), a `Dec` (`kit/dec.js`): a whole number of units at a
    scale, held in a BigInt. Adding, subtracting, comparing and rounding are exact, and the
    display functions format its digits as they are. It refuses to become a float by
    accident: arithmetic or a comparison with plain numbers throws, so a mistake fails loudly.
    What is only drawn (a chart's point, a bar's width) asks for a float by name. Sent back in a
    request, it is written as an exact number.
