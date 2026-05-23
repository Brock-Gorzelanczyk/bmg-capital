import type { Lesson, Course, Track } from "@/types/learn";

export const lessons: Lesson[] = [
  {
    id: "crypto-intro-l1",
    courseId: "crypto-intro",
    trackId: "crypto",
    title: "Crypto Fundamentals: What You're Actually Buying",
    type: "article",
    xp: 60,
    durationMin: 10,
    tags: ["crypto", "bitcoin", "blockchain", "ethereum", "defi"],
    body: `
<h2>Beyond the Price Ticker</h2>
<p>Most people who "invest" in crypto have no idea what they own. That's a problem — not because crypto is inherently bad, but because understanding the asset is the most basic prerequisite for investing in it.</p>

<div class="lesson-callout info">
  <strong>What Bitcoin actually is:</strong>
  <ul>
    <li>A <strong>decentralized, fixed-supply digital currency</strong> secured by cryptographic proof of work</li>
    <li>No central issuer (unlike dollars, which the Federal Reserve controls)</li>
    <li>21 million maximum supply — ever. Currently ~19.7M mined.</li>
    <li>Transactions are recorded permanently on a public blockchain that anyone can audit</li>
  </ul>
  Bitcoin is best understood as "digital gold" — a speculative store of value, not a payment network.
</div>

<div class="lesson-callout info">
  <strong>What Ethereum is:</strong>
  <ul>
    <li>A <strong>programmable blockchain</strong> — a decentralized computing platform</li>
    <li>Smart contracts: code that executes automatically when conditions are met, without a middleman</li>
    <li>Powers DeFi (decentralized finance), NFTs, and thousands of decentralized applications</li>
    <li>No fixed supply (unlike Bitcoin)</li>
  </ul>
</div>

<h2>The Risk Profile</h2>
<p>Crypto assets are among the most volatile asset classes in history. Bitcoin has experienced 8 separate drawdowns of 50%+ since 2011. Anyone allocating to crypto must be prepared for this volatility and size positions accordingly (most financial advisors suggest 1–5% of a portfolio, maximum).</p>

<div class="lesson-callout warning">
  <strong>Not all crypto is alike:</strong> Bitcoin and Ethereum have established track records. Most altcoins are speculative ventures that have gone to zero. 95%+ of all crypto projects that existed in 2018 are now worthless. Stick to liquid, established assets unless you're making a deliberate high-risk bet.
</div>
    `,
    quiz: [
      {
        id: "crypto-intro-l1-q1",
        question: "Bitcoin's maximum supply is:",
        options: ["Unlimited — the algorithm adjusts", "21 million", "1 billion", "Set by the Federal Reserve"],
        answer: 1,
        explanation: "Bitcoin has a hard-coded maximum supply of 21 million coins. This fixed supply is central to the 'digital gold' thesis — unlike fiat currencies, Bitcoin cannot be inflated by any authority.",
      },
      {
        id: "crypto-intro-l1-q2",
        question: "Ethereum's primary differentiation from Bitcoin is:",
        options: [
          "Lower transaction fees", "It's a programmable blockchain supporting smart contracts and decentralized apps", "Faster mining speed", "It's backed by a government"],
        answer: 1,
        explanation: "Ethereum is programmable — it supports smart contracts (self-executing code) that power DeFi, NFTs, and thousands of decentralized applications. Bitcoin is primarily digital currency/store of value.",
      },
      {
        id: "crypto-intro-l1-q3",
        question: "Most financial advisors suggest a crypto allocation of:",
        options: ["25–50% of portfolio for maximum returns", "10–15% for growth investors", "1–5% maximum due to volatility", "None — crypto is not a legitimate asset class"],
        answer: 2,
        explanation: "Given extreme volatility (50%+ drawdowns common), most advisors recommend limiting crypto to 1–5% of a diversified portfolio — enough to meaningfully participate if crypto performs well, but not enough to derail your financial plan if it doesn't.",
      },
    ],
  },
  {
    id: "crypto-intro-l2",
    courseId: "crypto-intro",
    trackId: "crypto",
    title: "On-Chain vs. Exchange: Custody and Security",
    type: "article",
    xp: 60,
    durationMin: 8,
    tags: ["custody", "self-custody", "hardware-wallet", "exchange-risk", "security"],
    body: `
<h2>Not Your Keys, Not Your Coins</h2>
<p>When you hold crypto on an exchange (Coinbase, Binance, etc.), you don't actually own the crypto — you own an IOU from the exchange. If the exchange gets hacked, goes bankrupt, or freezes withdrawals, your funds may be gone. This is not hypothetical: FTX, Celsius, Voyager, and Mt. Gox are all examples of exchange failures that wiped out billions in customer funds.</p>

<div class="lesson-callout info">
  <strong>Self-custody options:</strong>
  <ul>
    <li><strong>Software wallet (hot):</strong> Apps like MetaMask. Convenient, but connected to the internet — hackable. Use for small amounts and active DeFi usage.</li>
    <li><strong>Hardware wallet (cold):</strong> Ledger, Trezor. Stores private keys offline. More secure. Appropriate for larger holdings.</li>
  </ul>
</div>

<h2>The Seed Phrase: Your Master Key</h2>
<p>Every self-custody wallet generates a 12 or 24-word seed phrase. This phrase is the master key to all funds in that wallet. Write it on paper, store it in a fireproof location, never photograph it or store it digitally. Anyone who has your seed phrase owns all your crypto. There is no customer service. There is no recovery.</p>

<div class="lesson-callout warning">
  <strong>The tradeoff:</strong> Self-custody gives you full control and full responsibility. Exchange custody is convenient and has some consumer protections but introduces counterparty risk. Neither is perfect.
</div>
    `,
    quiz: [
      {
        id: "crypto-intro-l2-q1",
        question: "Holding crypto on an exchange means you actually own:",
        options: [
          "The actual cryptocurrency on the blockchain",
          "An IOU from the exchange — the exchange controls the actual private keys",
          "A certificate of ownership",
          "A fractional share of the exchange",
        ],
        answer: 1,
        explanation: "Exchange-held crypto means the exchange controls the private keys. If the exchange fails (FTX, Mt. Gox), customer funds may be lost. 'Not your keys, not your coins.'",
      },
      {
        id: "crypto-intro-l2-q2",
        question: "A hardware wallet is considered 'cold storage' because:",
        options: [
          "It stores crypto at below-freezing temperatures",
          "It stores private keys offline — not connected to the internet",
          "It requires cooling fans to operate",
          "Transactions are delayed by 24 hours for security",
        ],
        answer: 1,
        explanation: "Cold storage means the private keys are offline — physically disconnected from the internet and therefore not hackable remotely. Hardware wallets (Ledger, Trezor) are the most common cold storage solution.",
      },
      {
        id: "crypto-intro-l2-q3",
        question: "Your seed phrase should be:",
        options: [
          "Stored in your email drafts for safekeeping",
          "Written on paper and stored in a secure physical location, never digitally",
          "Memorized and never written down",
          "Shared with your broker for account recovery",
        ],
        answer: 1,
        explanation: "Seed phrases must be stored offline on paper in a secure location. Any digital storage (email, photo, cloud) creates hack risk. Your seed phrase = complete access to all funds in the wallet.",
      },
    ],
  },
];

export const courses: Course[] = [
  {
    id: "crypto-intro",
    trackId: "crypto",
    title: "Crypto Foundations",
    description: "What crypto actually is, how to evaluate projects, and how to hold it securely.",
    lessonIds: ["crypto-intro-l1", "crypto-intro-l2"],
    xpTotal: 120,
  },
];

export const track: Track = {
  id: "crypto",
  title: "Crypto & Digital Assets",
  description: "What Bitcoin and Ethereum actually are, how blockchain works, DeFi basics, and how to hold crypto securely.",
  icon: "₿",
  difficulty: "beginner",
  colorClass: "orange",
  courseIds: ["crypto-intro"],
};
