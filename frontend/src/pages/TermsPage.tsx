import { Link } from "react-router-dom";
import { AlertTriangle, FileText } from "lucide-react";

export default function TermsPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <div className="max-w-3xl mx-auto px-4 py-16 space-y-10">

        {/* Header */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-zinc-500 text-sm">
            <FileText className="w-4 h-4" />
            <span>Legal</span>
          </div>
          <h1 className="text-3xl md:text-4xl font-black tracking-tight">Terms of Service</h1>
          <p className="text-zinc-400 text-sm">Last updated: June 2026</p>
          <div className="flex flex-wrap gap-3 text-sm pt-1">
            <Link to="/" className="text-blue-400 hover:text-blue-300 underline underline-offset-2">
              Back to app
            </Link>
            <span className="text-zinc-700">·</span>
            <Link to="/privacy" className="text-blue-400 hover:text-blue-300 underline underline-offset-2">
              Privacy Policy
            </Link>
          </div>
        </div>

        {/* Paper trading callout */}
        <div className="bg-amber-950/30 border border-amber-500/30 rounded-2xl p-5 flex gap-4">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-amber-200/80 text-sm leading-relaxed">
            <span className="font-bold text-amber-300">Important:</span> BMG Capital is a paper
            trading simulation platform. No real money is ever traded, invested, or managed on this
            platform. All trading activity is entirely simulated for educational purposes.
          </p>
        </div>

        {/* Sections */}
        <div className="space-y-8 text-sm leading-relaxed text-zinc-300">

          <Section number="1" title="Acceptance of Terms">
            <p>
              By accessing or using the BMG Capital platform (the "Service"), including the website,
              web application, APIs, and any related services, you agree to be bound by these Terms
              of Service ("Terms"). If you do not agree to these Terms, do not access or use the
              Service.
            </p>
            <p className="mt-3">
              These Terms constitute a legally binding agreement between you ("User," "you," or
              "your") and BMG Capital ("BMG Capital," "we," "us," or "our"). Your continued use of
              the Service following any modification to these Terms constitutes acceptance of those
              modifications.
            </p>
          </Section>

          <Section number="2" title="Paper Trading Only — Not Investment Advice">
            <p>
              <span className="font-semibold text-white">ALL trading activity on this platform is
              simulated paper trading.</span> No real money is traded, invested, managed, or placed
              at risk at any time. BMG Capital does not hold, transmit, or manage any real currency
              or financial assets on behalf of users.
            </p>
            <p className="mt-3">
              BMG Capital is an educational and simulation tool designed to help individuals learn
              about trading strategies, portfolio management, and financial markets in a risk-free
              environment. The platform provides simulated market data, AI-assisted analysis, and
              strategy backtesting for learning purposes only.
            </p>
            <p className="mt-3">
              Nothing on this platform — including strategy signals, AI analysis, bot activity,
              journal recommendations, analyst reports, or any other content — constitutes
              investment advice, financial advice, trading advice, legal advice, tax advice, or any
              other form of professional advice. You should not rely on any information or outputs
              from this platform to make real investment or financial decisions.
            </p>
            <p className="mt-3">
              Past simulated performance does not guarantee, predict, or suggest future results,
              whether in simulated or real trading. All simulated performance figures are
              hypothetical and do not reflect actual investment returns. Hypothetical performance
              results have many inherent limitations, including that they do not reflect the impact
              of actual market liquidity constraints, fees, or execution slippage.
            </p>
            <p className="mt-3">
              BMG Capital is not registered as an investment adviser, broker-dealer, or financial
              planner with any regulatory authority. Live trading functionality, if introduced in
              the future, will be subject to separate terms and applicable regulatory requirements.
            </p>
          </Section>

          <Section number="3" title="Account Registration">
            <p>
              You must be at least 18 years of age to create an account and use the Service. By
              registering, you represent and warrant that you are 18 or older and that all
              information you provide during registration is accurate, complete, and current.
            </p>
            <p className="mt-3">
              You may maintain only one account per person. Creating multiple accounts to circumvent
              usage limits, trial restrictions, or account suspensions is prohibited and may result
              in permanent termination of all associated accounts.
            </p>
            <p className="mt-3">
              You are solely responsible for maintaining the confidentiality of your account
              credentials, including your password. You are responsible for all activity that
              occurs under your account. You must notify us immediately at{" "}
              <a href="mailto:legal@bmgcapital.com" className="text-blue-400 hover:text-blue-300 underline">
                legal@bmgcapital.com
              </a>{" "}
              if you suspect unauthorized use of your account. BMG Capital is not liable for any
              loss or damage arising from your failure to protect your account credentials.
            </p>
          </Section>

          <Section number="4" title="Acceptable Use">
            <p>You agree not to:</p>
            <ul className="mt-3 space-y-2 list-none">
              {[
                "Reverse engineer, decompile, disassemble, or attempt to derive the source code of the Service or any underlying algorithms, AI models, or proprietary systems.",
                "Scrape, crawl, or systematically extract data from the Service by automated means without our prior written consent.",
                "Abuse, exploit, or attempt to circumvent rate limits, API quotas, subscription restrictions, or any other usage controls.",
                "Submit abusive, harmful, or misleading inputs to AI features (including the AI Co-Pilot, AI Analyst, and Voice AI) or attempt to manipulate AI outputs for malicious purposes.",
                "Use the Service to develop competing products or services without express written authorization.",
                "Impersonate any person or entity or misrepresent your affiliation with any person or entity.",
                "Transmit any malicious code, malware, or other harmful content through the Service.",
                "Use the Service for any unlawful purpose or in violation of any applicable laws or regulations.",
                "Attempt to gain unauthorized access to any part of the Service, its servers, databases, or connected systems.",
              ].map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <span className="text-zinc-600 mt-0.5 shrink-0">—</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3">
              Violation of these acceptable use restrictions may result in immediate suspension or
              termination of your account without notice or refund.
            </p>
          </Section>

          <Section number="5" title="Intellectual Property">
            <p>
              All content, features, and functionality of the Service — including but not limited
              to the text, graphics, logos, icons, images, audio clips, data compilations, software
              code, AI models, machine learning algorithms, trading strategies, backtesting
              methodologies, screener logic, and the selection and arrangement thereof — are owned
              by BMG Capital or its licensors and are protected by applicable copyright, trademark,
              patent, trade secret, and other intellectual property laws.
            </p>
            <p className="mt-3">
              Your use of the Service does not grant you any ownership interest in or license to
              any intellectual property of BMG Capital beyond the limited right to use the Service
              as expressly set forth in these Terms. You may not copy, reproduce, distribute,
              modify, create derivative works of, publicly display, publicly perform, republish,
              download, store, or transmit any materials from the Service except as expressly
              permitted by these Terms.
            </p>
            <p className="mt-3">
              BMG Capital respects intellectual property rights and expects users to do the same.
              If you believe any content on the Service infringes your intellectual property rights,
              please contact us at{" "}
              <a href="mailto:legal@bmgcapital.com" className="text-blue-400 hover:text-blue-300 underline">
                legal@bmgcapital.com
              </a>.
            </p>
          </Section>

          <Section number="6" title="Disclaimer of Warranties">
            <p className="font-semibold text-zinc-200 uppercase tracking-wide text-xs">
              The following section limits our liability. Please read it carefully.
            </p>
            <p className="mt-3">
              THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND,
              EITHER EXPRESS OR IMPLIED. TO THE FULLEST EXTENT PERMITTED BY APPLICABLE LAW, BMG
              CAPITAL DISCLAIMS ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
              IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE,
              NON-INFRINGEMENT, AND TITLE.
            </p>
            <p className="mt-3">
              BMG CAPITAL DOES NOT WARRANT THAT: (A) THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE,
              OR SECURE; (B) DEFECTS WILL BE CORRECTED; (C) THE SERVICE OR THE SERVER THAT MAKES
              IT AVAILABLE IS FREE OF VIRUSES OR OTHER HARMFUL COMPONENTS; (D) THE RESULTS OBTAINED
              FROM USE OF THE SERVICE WILL BE ACCURATE, RELIABLE, OR SUITABLE FOR ANY PARTICULAR
              PURPOSE; OR (E) ANY SIMULATED TRADING RESULTS WILL REFLECT REAL-WORLD MARKET
              CONDITIONS.
            </p>
          </Section>

          <Section number="7" title="Limitation of Liability">
            <p>
              TO THE FULLEST EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL BMG CAPITAL,
              ITS OFFICERS, DIRECTORS, EMPLOYEES, AGENTS, LICENSORS, OR SERVICE PROVIDERS BE LIABLE
              FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, PUNITIVE, OR EXEMPLARY DAMAGES,
              INCLUDING BUT NOT LIMITED TO LOSS OF PROFITS, LOSS OF REVENUE, LOSS OF DATA, LOSS OF
              GOODWILL, BUSINESS INTERRUPTION, OR ANY OTHER INTANGIBLE LOSSES, ARISING OUT OF OR IN
              CONNECTION WITH YOUR USE OF OR INABILITY TO USE THE SERVICE.
            </p>
            <p className="mt-3">
              THIS LIMITATION APPLIES REGARDLESS OF WHETHER SUCH DAMAGES ARISE FROM BREACH OF
              CONTRACT, TORT (INCLUDING NEGLIGENCE), STRICT LIABILITY, OR ANY OTHER LEGAL THEORY,
              AND EVEN IF BMG CAPITAL HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.
            </p>
            <p className="mt-3">
              IN PARTICULAR, BMG CAPITAL SHALL NOT BE LIABLE FOR ANY LOSS OR DAMAGE ARISING FROM:
              (A) YOUR RELIANCE ON SIMULATED TRADING RESULTS TO MAKE ACTUAL INVESTMENT DECISIONS;
              (B) DECISIONS YOU MAKE BASED ON AI-GENERATED ANALYSIS, STRATEGY SIGNALS, OR ANY OTHER
              CONTENT PROVIDED BY THE SERVICE; (C) ANY REAL FINANCIAL LOSSES YOU INCUR AS A RESULT
              OF USING OR RELYING ON THE SERVICE IN ANY WAY; OR (D) UNAUTHORIZED ACCESS TO YOUR
              ACCOUNT DATA.
            </p>
            <p className="mt-3">
              IN JURISDICTIONS THAT DO NOT ALLOW THE EXCLUSION OR LIMITATION OF CERTAIN DAMAGES,
              OUR LIABILITY IS LIMITED TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW. IN ALL
              CASES, OUR TOTAL LIABILITY TO YOU SHALL NOT EXCEED THE GREATER OF (A) THE TOTAL
              AMOUNT YOU PAID TO BMG CAPITAL IN THE TWELVE MONTHS PRECEDING THE CLAIM, OR (B)
              ONE HUNDRED U.S. DOLLARS ($100).
            </p>
          </Section>

          <Section number="8" title="Termination">
            <p>
              We reserve the right to suspend or terminate your account and access to the Service,
              at our sole discretion, at any time and without prior notice, for any reason,
              including but not limited to: violation of these Terms, suspected fraudulent or
              abusive activity, prolonged inactivity, or non-payment of applicable fees.
            </p>
            <p className="mt-3">
              Upon termination, your right to access and use the Service will immediately cease.
              Provisions of these Terms that by their nature should survive termination shall
              survive, including ownership provisions, warranty disclaimers, indemnity obligations,
              and limitations of liability.
            </p>
            <p className="mt-3">
              You may terminate your account at any time by contacting us or using the account
              deletion option in Settings. Upon your request, we will delete your account data
              subject to any legal retention obligations.
            </p>
          </Section>

          <Section number="9" title="Changes to Terms">
            <p>
              We reserve the right to modify these Terms at any time. When we make material changes,
              we will update the "Last updated" date at the top of this page and, where appropriate,
              provide additional notice such as an in-app notification or email.
            </p>
            <p className="mt-3">
              Your continued access to or use of the Service after any modification to these Terms
              constitutes your acceptance of the updated Terms. If you do not agree to the modified
              Terms, you must stop using the Service.
            </p>
            <p className="mt-3">
              We encourage you to review these Terms periodically to stay informed of any updates.
            </p>
          </Section>

          <Section number="10" title="Contact">
            <p>
              If you have questions or concerns about these Terms of Service, please contact us:
            </p>
            <div className="mt-4 bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-1">
              <p className="font-semibold text-zinc-200">BMG Capital</p>
              <p>
                Email:{" "}
                <a
                  href="mailto:legal@bmgcapital.com"
                  className="text-blue-400 hover:text-blue-300 underline"
                >
                  legal@bmgcapital.com
                </a>
              </p>
            </div>
          </Section>

        </div>

        {/* Footer nav */}
        <div className="border-t border-zinc-800 pt-8 flex flex-wrap gap-4 text-sm text-zinc-500">
          <Link to="/" className="hover:text-zinc-300 transition-colors">
            Back to BMG Capital
          </Link>
          <span>·</span>
          <Link to="/privacy" className="hover:text-zinc-300 transition-colors">
            Privacy Policy
          </Link>
          <span>·</span>
          <a href="mailto:legal@bmgcapital.com" className="hover:text-zinc-300 transition-colors">
            legal@bmgcapital.com
          </a>
        </div>

      </div>
    </div>
  );
}

function Section({
  number,
  title,
  children,
}: {
  number: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-0">
      <h2 className="text-base font-bold text-white mb-3">
        <span className="text-zinc-600 font-normal mr-2">{number}.</span>
        {title}
      </h2>
      <div className="text-zinc-300">{children}</div>
    </section>
  );
}
