import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, FileText, Shield, AlertTriangle, DollarSign, Scale, Mail } from 'lucide-react';
import { Button } from '../components/ui/button';

const Terms = () => {
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-b from-zinc-950 via-zinc-900 to-zinc-950">
      {/* Header */}
      <header className="border-b border-white/5 bg-zinc-950/80 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <Link to="/" className="flex items-center gap-2 text-zinc-400 hover:text-white transition-colors">
              <ArrowLeft className="w-4 h-4" />
              Back to Home
            </Link>
            <Link to="/privacy" className="text-sm text-emerald-400 hover:text-emerald-300">
              Privacy Policy →
            </Link>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Title */}
        <div className="text-center mb-12">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-r from-violet-500/20 to-emerald-500/20 mb-6">
            <FileText className="w-8 h-8 text-emerald-400" />
          </div>
          <h1 className="text-3xl md:text-4xl font-bold text-white mb-4">Terms & Conditions</h1>
          <p className="text-zinc-400">Last updated: January 2025</p>
        </div>

        {/* Terms Content */}
        <div className="prose prose-invert prose-zinc max-w-none">
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-6 md:p-8 space-y-8">
            
            {/* Introduction */}
            <section>
              <p className="text-zinc-300 leading-relaxed">
                Welcome to Covered Call Engine (CCE). These Terms & Conditions ("Terms") govern your access to and use of the Covered Call Engine website, platform, tools, and services (collectively, the "Service"). By accessing, registering, or subscribing to any plan (including the FREE Trial), you acknowledge that you have read, understood, and agreed to be bound by these Terms.
              </p>
              <p className="text-amber-400 font-medium mt-4">
                If you do not agree to these Terms, you must not use or subscribe to the Service.
              </p>
            </section>

            {/* Section 1 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">1</span>
                Acceptance of Terms
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                By creating an account, accessing the platform, or subscribing to any CCE plan (including the FREE Trial), you confirm that you:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400">
                <li>Are at least 18 years of age;</li>
                <li>Have the legal capacity to enter into a binding agreement; and</li>
                <li>Agree to comply with these Terms in full.</li>
              </ul>
              <p className="text-zinc-300 mt-4 font-medium">
                Acceptance of these Terms is mandatory before any subscription can be activated.
              </p>
            </section>

            {/* Section 2 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">2</span>
                Nature of the Service
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                Covered Call Engine (CCE) provides:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-4">
                <li>A research and analysis tool designed to assist users in exploring covered call strategies;</li>
                <li>Market data visualisation, screening, and filtering capabilities; and</li>
                <li>Educational and informational insights to support independent decision-making.</li>
              </ul>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE does <strong className="text-red-400">NOT</strong>:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400">
                <li>Provide trading signals;</li>
                <li>Recommend or advise you to enter, exit, or modify any trade;</li>
                <li>Execute trades on your behalf; or</li>
                <li>Act as a broker, dealer, or financial advisor.</li>
              </ul>
              <p className="text-zinc-300 mt-4 italic">
                All information provided is for general informational and research purposes only.
              </p>
            </section>

            {/* Section 3 */}
            <section className="bg-red-500/10 border border-red-500/20 rounded-xl p-6">
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <AlertTriangle className="w-6 h-6 text-red-400" />
                <span>3. No Financial Advice</span>
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE is not a financial advisor, investment advisor, broker, or dealer. We do not know your personal financial situation, investment objectives, risk tolerance, or financial needs.
              </p>
              <p className="text-zinc-300 leading-relaxed mb-4">
                Nothing on this platform should be construed as:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400">
                <li>Financial advice;</li>
                <li>Investment advice;</li>
                <li>Legal advice; or</li>
                <li>Tax advice.</li>
              </ul>
              <p className="text-amber-400 mt-4 font-medium">
                You are solely responsible for evaluating whether any strategy, security, or trade is suitable for you. We strongly recommend that you consult with a licensed financial professional before making any trading or investment decisions.
              </p>
            </section>

            {/* Section 4 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">4</span>
                Market Coverage Limitation
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE focuses exclusively on the U.S. financial markets, including:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400">
                <li>U.S. listed Stocks;</li>
                <li>U.S. listed ETFs; and</li>
                <li>U.S. listed Indices.</li>
              </ul>
              <p className="text-zinc-300 mt-4">
                CCE does not provide coverage, analysis, or data for non-U.S. markets.
              </p>
            </section>

            {/* Section 5 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">5</span>
                Third-Party Data & Accuracy Disclaimer
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE relies on third-party data providers for market prices, options chains, volatility metrics, and other financial information.
              </p>
              <p className="text-zinc-300 leading-relaxed mb-4">
                While we perform reasonable due diligence to ensure data quality:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-4">
                <li>We do not guarantee the accuracy, completeness, timeliness, or reliability of third-party data;</li>
                <li>Data may be delayed, incorrect, incomplete, or subject to outages;</li>
                <li>CCE is not responsible for any errors, omissions, or discrepancies in third-party data.</li>
              </ul>
              <p className="text-zinc-300 leading-relaxed mb-4">
                You are solely responsible for:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400">
                <li>Independently verifying all information; and</li>
                <li>Confirming prices, contracts, and trade details with your broker or the relevant exchange before placing any trade.</li>
              </ul>
            </section>

            {/* Section 6 */}
            <section className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-6">
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <AlertTriangle className="w-6 h-6 text-amber-400" />
                <span>6. Options Trading Risk Disclaimer</span>
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                Options trading involves significant risk and is not suitable for all investors. Risks may include, but are not limited to:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-4">
                <li>Loss of the entire premium paid;</li>
                <li>Rapid losses due to market volatility;</li>
                <li>Assignment risk;</li>
                <li>Liquidity risk; and</li>
                <li>Complex tax implications.</li>
              </ul>
              <p className="text-zinc-300 leading-relaxed mb-4">
                You acknowledge that:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-4">
                <li>Past performance is not indicative of future results;</li>
                <li>You are responsible for educating yourself about options trading; and</li>
                <li>You should seek professional assistance where necessary.</li>
              </ul>
              <p className="text-amber-400 font-medium">
                By using CCE, you confirm that you understand and accept the risks associated with options trading.
              </p>
            </section>

            {/* Section 7 */}
            <section className="bg-violet-500/10 border border-violet-500/20 rounded-xl p-6">
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <DollarSign className="w-6 h-6 text-violet-400" />
                <span>7. FREE Trial & No Refund Policy</span>
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE may offer a FREE Trial to allow users to evaluate the platform before committing to a paid subscription.
              </p>
              <p className="text-zinc-300 leading-relaxed mb-4">
                By subscribing, you agree that:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-4">
                <li>The FREE Trial is provided to test and assess suitability;</li>
                <li>No refunds will be provided for any paid subscription under any circumstances;</li>
                <li>Dissatisfaction with features, data, performance, or outcomes does not qualify for a refund.</li>
              </ul>
              <p className="text-violet-400 font-medium">
                All subscription fees are final and non-refundable.
              </p>
            </section>

            {/* Section 8 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">8</span>
                User Responsibility & Assumption of Risk
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                You acknowledge and agree that:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-4">
                <li>All trading and investment decisions are made solely by you;</li>
                <li>You assume full responsibility for any gains, losses, or outcomes;</li>
                <li>CCE and its team are not liable for any financial losses, missed opportunities, or adverse outcomes.</li>
              </ul>
              <p className="text-zinc-300">
                You agree to hold harmless Covered Call Engine, its founders, employees, contractors, affiliates, and partners from any claims, damages, or losses arising from your use of the Service.
              </p>
            </section>

            {/* Section 9 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">9</span>
                Limitation of Liability
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                To the maximum extent permitted by law:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-4">
                <li>CCE shall not be liable for any direct, indirect, incidental, consequential, or punitive damages;</li>
                <li>Including but not limited to loss of capital, profits, data, or business opportunities;</li>
                <li>Even if CCE has been advised of the possibility of such damages.</li>
              </ul>
              <p className="text-amber-400 font-medium">
                Your use of the Service is entirely at your own risk.
              </p>
            </section>

            {/* Section 10 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">10</span>
                Support & Communication
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE provides a customer support system for technical or platform-related issues.
              </p>
              <p className="text-zinc-300 leading-relaxed mb-4">
                If you experience any issues:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-4">
                <li>Contact us via the official support channels listed on the website;</li>
                <li>One of our support agents will respond within a reasonable timeframe.</li>
              </ul>
              <p className="text-zinc-400 italic">
                Support does not include trading advice, trade validation, or personalised investment guidance.
              </p>
            </section>

            {/* Section 11 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">11</span>
                Account Termination
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE reserves the right to:
              </p>
              <ul className="list-disc pl-6 space-y-2 text-zinc-400">
                <li>Suspend or terminate accounts that violate these Terms;</li>
                <li>Restrict access for misuse, abuse, or unlawful activity;</li>
                <li>Modify or discontinue the Service at any time without liability.</li>
              </ul>
            </section>

            {/* Section 12 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <span className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400 text-sm">12</span>
                Modifications to Terms
              </h2>
              <p className="text-zinc-300 leading-relaxed">
                CCE may update these Terms from time to time. Continued use of the Service after changes are published constitutes acceptance of the revised Terms.
              </p>
            </section>

            {/* Section 13 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <Scale className="w-6 h-6 text-emerald-400" />
                <span>13. Governing Law</span>
              </h2>
              <p className="text-zinc-300 leading-relaxed">
                These Terms shall be governed by and construed in accordance with the laws of the applicable jurisdiction in which Covered Call Engine operates, without regard to conflict of law principles.
              </p>
            </section>

            {/* Section 14 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-2 mb-4">
                <Mail className="w-6 h-6 text-emerald-400" />
                <span>14. Contact Information</span>
              </h2>
              <p className="text-zinc-300 leading-relaxed">
                For questions regarding these Terms & Conditions, please contact us through the official communication channels provided on the CCE website.
              </p>
            </section>

            {/* Final Agreement */}
            <section className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-6 text-center">
              <p className="text-emerald-400 font-semibold text-lg">
                By subscribing to or using Covered Call Engine, you confirm that you have read, understood, and agreed to all the Terms & Conditions above.
              </p>
            </section>

            {/* Appendix A */}
            <section className="border-t border-zinc-700 pt-8">
              <h2 className="text-2xl font-bold text-white mb-6 flex items-center gap-2">
                <AlertTriangle className="w-6 h-6 text-amber-400" />
                Appendix A – Risk Disclosure Statement
              </h2>
              
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-semibold text-white mb-3">A1. General Risk Disclosure</h3>
                  <p className="text-zinc-300 leading-relaxed">
                    Trading in securities and options involves substantial risk and may not be suitable for all individuals. You acknowledge that you may lose some or all of your invested capital and that no representation is made that any strategy, model, or analysis will achieve profits or avoid losses.
                  </p>
                  <p className="text-zinc-300 leading-relaxed mt-3">
                    Covered Call Engine (CCE) provides tools and information for research purposes only. Any outcomes achieved using the platform are dependent on market conditions, user decisions, execution quality, and risk management practices beyond CCE's control.
                  </p>
                </div>

                <div>
                  <h3 className="text-lg font-semibold text-white mb-3">A2. Options-Specific Risks</h3>
                  <p className="text-zinc-300 leading-relaxed mb-3">
                    Options trading carries unique and complex risks, including but not limited to:
                  </p>
                  <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-3">
                    <li>Market volatility causing rapid price movements;</li>
                    <li>Assignment risk on short option positions;</li>
                    <li>Liquidity constraints impacting entry and exit;</li>
                    <li>Changes in implied volatility;</li>
                    <li>Early assignment and corporate action risks.</li>
                  </ul>
                  <p className="text-zinc-300 leading-relaxed">
                    You confirm that you understand these risks and have reviewed appropriate options disclosure documents, including those provided by your broker or relevant exchange.
                  </p>
                </div>

                <div>
                  <h3 className="text-lg font-semibold text-white mb-3">A3. No Performance Guarantees</h3>
                  <p className="text-zinc-300 leading-relaxed mb-3">
                    CCE does not guarantee:
                  </p>
                  <ul className="list-disc pl-6 space-y-2 text-zinc-400 mb-3">
                    <li>Accuracy of projections or calculations;</li>
                    <li>Profitability of any strategy;</li>
                    <li>Risk reduction outcomes; or</li>
                    <li>Consistency of results.</li>
                  </ul>
                  <p className="text-zinc-300 leading-relaxed">
                    Historical data, backtesting, or hypothetical scenarios shown on the platform do not represent actual trading results and should not be relied upon as indicators of future performance.
                  </p>
                </div>

                <div>
                  <h3 className="text-lg font-semibold text-white mb-3">A4. Independent Verification Required</h3>
                  <p className="text-zinc-300 leading-relaxed mb-3">
                    All users must independently verify:
                  </p>
                  <ul className="list-disc pl-6 space-y-2 text-zinc-400">
                    <li>Security prices;</li>
                    <li>Options contract specifications;</li>
                    <li>Margin requirements; and</li>
                    <li>Order execution details</li>
                  </ul>
                  <p className="text-zinc-300 leading-relaxed mt-3">
                    with their broker or the relevant securities exchange prior to placing any trade.
                  </p>
                </div>

                <div>
                  <h3 className="text-lg font-semibold text-white mb-3">A5. Professional Advice</h3>
                  <p className="text-zinc-300 leading-relaxed">
                    You are strongly encouraged to seek independent advice from licensed financial, legal, or tax professionals to determine whether any trading strategy is appropriate for your individual circumstances.
                  </p>
                </div>
              </div>
            </section>

          </div>
        </div>

        {/* Back to Home */}
        <div className="mt-12 text-center">
          <Link to="/">
            <Button className="bg-emerald-600 hover:bg-emerald-700">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Home
            </Button>
          </Link>
        </div>
      </main>
    </div>
  );
};

export default Terms;
