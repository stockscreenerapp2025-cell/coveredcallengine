import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Shield, Database, Share2, Lock, UserCheck, CheckCircle } from 'lucide-react';
import { Button } from '../components/ui/button';

const Privacy = () => {
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
            <Link to="/terms" className="text-sm text-emerald-400 hover:text-emerald-300">
              ← Terms & Conditions
            </Link>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {/* Title */}
        <div className="text-center mb-12">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-r from-violet-500/20 to-emerald-500/20 mb-6">
            <Shield className="w-8 h-8 text-emerald-400" />
          </div>
          <h1 className="text-3xl md:text-4xl font-bold text-white mb-4">Privacy Policy</h1>
          <p className="text-zinc-400">Last updated: January 2025</p>
        </div>

        {/* Privacy Content */}
        <div className="prose prose-invert prose-zinc max-w-none">
          <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-6 md:p-8 space-y-8">
            
            {/* Introduction */}
            <section>
              <p className="text-zinc-300 leading-relaxed">
                At Covered Call Engine (CCE), we are committed to protecting your privacy and ensuring the security of your personal information. This Privacy Policy explains how we collect, use, and safeguard your data when you use our platform and services.
              </p>
            </section>

            {/* Section 1 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-blue-500/20 flex items-center justify-center">
                  <Database className="w-5 h-5 text-blue-400" />
                </div>
                1. Information We Collect
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE may collect the following information:
              </p>
              <div className="grid md:grid-cols-2 gap-4">
                <div className="bg-zinc-800/50 rounded-lg p-4">
                  <h4 className="text-white font-medium mb-2">Account Information</h4>
                  <p className="text-zinc-400 text-sm">Name, email address, login credentials</p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-4">
                  <h4 className="text-white font-medium mb-2">Subscription & Billing</h4>
                  <p className="text-zinc-400 text-sm">Payment details, subscription status, billing history</p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-4">
                  <h4 className="text-white font-medium mb-2">Usage Data</h4>
                  <p className="text-zinc-400 text-sm">Features accessed, search queries, saved preferences</p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-4">
                  <h4 className="text-white font-medium mb-2">Technical Data</h4>
                  <p className="text-zinc-400 text-sm">IP address, browser type, device information</p>
                </div>
              </div>
            </section>

            {/* Section 2 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-emerald-500/20 flex items-center justify-center">
                  <CheckCircle className="w-5 h-5 text-emerald-400" />
                </div>
                2. How We Use Your Information
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                We use collected information to:
              </p>
              <ul className="space-y-3">
                <li className="flex items-start gap-3">
                  <span className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <CheckCircle className="w-3 h-3 text-emerald-400" />
                  </span>
                  <span className="text-zinc-300">Provide and maintain the Service</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <CheckCircle className="w-3 h-3 text-emerald-400" />
                  </span>
                  <span className="text-zinc-300">Manage subscriptions and access control</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <CheckCircle className="w-3 h-3 text-emerald-400" />
                  </span>
                  <span className="text-zinc-300">Improve platform performance and features</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <CheckCircle className="w-3 h-3 text-emerald-400" />
                  </span>
                  <span className="text-zinc-300">Communicate service-related updates and announcements</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="w-6 h-6 rounded-full bg-emerald-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <CheckCircle className="w-3 h-3 text-emerald-400" />
                  </span>
                  <span className="text-zinc-300">Provide customer support</span>
                </li>
              </ul>
            </section>

            {/* Section 3 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-violet-500/20 flex items-center justify-center">
                  <Share2 className="w-5 h-5 text-violet-400" />
                </div>
                3. Data Sharing
              </h2>
              <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 mb-4">
                <p className="text-emerald-400 font-medium">
                  ✓ CCE does NOT sell your personal data.
                </p>
              </div>
              <p className="text-zinc-300 leading-relaxed mb-4">
                Information may be shared only:
              </p>
              <ul className="space-y-3">
                <li className="flex items-start gap-3">
                  <span className="text-zinc-500">•</span>
                  <span className="text-zinc-300">With trusted service providers (e.g., hosting, email, payment processors)</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="text-zinc-500">•</span>
                  <span className="text-zinc-300">To comply with legal or regulatory obligations</span>
                </li>
                <li className="flex items-start gap-3">
                  <span className="text-zinc-500">•</span>
                  <span className="text-zinc-300">To protect the rights, property, or safety of CCE and its users</span>
                </li>
              </ul>
            </section>

            {/* Section 4 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center">
                  <Lock className="w-5 h-5 text-amber-400" />
                </div>
                4. Data Security
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                CCE implements reasonable administrative, technical, and organisational measures to protect user data. These include:
              </p>
              <div className="grid md:grid-cols-3 gap-4">
                <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                  <Lock className="w-8 h-8 text-amber-400 mx-auto mb-2" />
                  <h4 className="text-white font-medium">Encryption</h4>
                  <p className="text-zinc-500 text-sm">Data in transit and at rest</p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                  <Shield className="w-8 h-8 text-amber-400 mx-auto mb-2" />
                  <h4 className="text-white font-medium">Access Controls</h4>
                  <p className="text-zinc-500 text-sm">Restricted data access</p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                  <Database className="w-8 h-8 text-amber-400 mx-auto mb-2" />
                  <h4 className="text-white font-medium">Secure Storage</h4>
                  <p className="text-zinc-500 text-sm">Protected databases</p>
                </div>
              </div>
              <p className="text-zinc-400 text-sm mt-4 italic">
                However, no system is completely secure, and we cannot guarantee absolute security.
              </p>
            </section>

            {/* Section 5 */}
            <section>
              <h2 className="text-xl font-semibold text-white flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-cyan-500/20 flex items-center justify-center">
                  <UserCheck className="w-5 h-5 text-cyan-400" />
                </div>
                5. User Rights
              </h2>
              <p className="text-zinc-300 leading-relaxed mb-4">
                You may request:
              </p>
              <div className="space-y-3">
                <div className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg">
                  <span className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                    <CheckCircle className="w-4 h-4 text-cyan-400" />
                  </span>
                  <span className="text-zinc-300">Access to your personal data</span>
                </div>
                <div className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg">
                  <span className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                    <CheckCircle className="w-4 h-4 text-cyan-400" />
                  </span>
                  <span className="text-zinc-300">Correction of inaccurate information</span>
                </div>
                <div className="flex items-center gap-3 p-3 bg-zinc-800/50 rounded-lg">
                  <span className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                    <CheckCircle className="w-4 h-4 text-cyan-400" />
                  </span>
                  <span className="text-zinc-300">Deletion of your account, subject to legal and operational requirements</span>
                </div>
              </div>
            </section>

            {/* Section 6 */}
            <section className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-6">
              <h2 className="text-xl font-semibold text-white flex items-center gap-3 mb-4">
                <Shield className="w-6 h-6 text-emerald-400" />
                6. Privacy Acceptance
              </h2>
              <p className="text-emerald-400 font-medium">
                By using the CCE platform, you consent to the collection and use of information as described in this Privacy Policy.
              </p>
            </section>

            {/* Contact */}
            <section className="text-center border-t border-zinc-700 pt-8">
              <h3 className="text-lg font-semibold text-white mb-4">Questions About Privacy?</h3>
              <p className="text-zinc-400 mb-4">
                If you have any questions about this Privacy Policy or how we handle your data, please contact us through the official communication channels on our website.
              </p>
            </section>

          </div>
        </div>

        {/* Back to Home */}
        <div className="mt-12 text-center space-x-4">
          <Link to="/terms">
            <Button variant="outline" className="btn-outline">
              View Terms & Conditions
            </Button>
          </Link>
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

export default Privacy;
