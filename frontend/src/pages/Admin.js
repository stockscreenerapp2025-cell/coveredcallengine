--- frontend/Admin.js
+++ frontend/Admin.js
@@
   const [integrationSettings, setIntegrationSettings] = useState({
     stripe_webhook_secret: '',
     stripe_secret_key: '',
     resend_api_key: '',
-    sender_email: ''
+    sender_email: '',
+    paypal_enabled: true,
+    paypal_mode: 'sandbox',
+    paypal_api_username: '',
+    paypal_api_password: '',
+    paypal_api_signature: ''
   });
@@
-  const [showResendKey, setShowResendKey] = useState(false);
+  const [showResendKey, setShowResendKey] = useState(false);
+  const [showPayPalPassword, setShowPayPalPassword] = useState(false);
+  const [showPayPalSignature, setShowPayPalSignature] = useState(false);
@@
   const saveIntegrationSettings = async () => {
     setSavingIntegration(true);
     try {
       const params = new URLSearchParams();
       if (integrationSettings.stripe_webhook_secret) params.append('stripe_webhook_secret', integrationSettings.stripe_webhook_secret);
       if (integrationSettings.stripe_secret_key) params.append('stripe_secret_key', integrationSettings.stripe_secret_key);
       if (integrationSettings.resend_api_key) params.append('resend_api_key', integrationSettings.resend_api_key);
       if (integrationSettings.sender_email) params.append('sender_email', integrationSettings.sender_email);
+      if (integrationSettings.paypal_enabled !== undefined) params.append('paypal_enabled', String(integrationSettings.paypal_enabled));
+      if (integrationSettings.paypal_mode) params.append('paypal_mode', integrationSettings.paypal_mode);
+      if (integrationSettings.paypal_api_username) params.append('paypal_api_username', integrationSettings.paypal_api_username);
+      if (integrationSettings.paypal_api_password) params.append('paypal_api_password', integrationSettings.paypal_api_password);
+      if (integrationSettings.paypal_api_signature) params.append('paypal_api_signature', integrationSettings.paypal_api_signature);
       
       await api.post(`/admin/integration-settings?${params.toString()}`);
       toast.success('Integration settings saved');
       fetchIntegrationSettings();
@@
             <Card className={`glass-card border-l-4 ${integrationStatus?.email?.resend_api_key_configured ? 'border-emerald-500' : 'border-yellow-500'}`}>
               <CardContent className="p-4">
                 <div className="flex items-center gap-3">
@@
                 </div>
               </CardContent>
             </Card>
+            <Card className={`glass-card border-l-4 ${integrationStatus?.paypal?.configured ? 'border-emerald-500' : 'border-yellow-500'}`}>
+              <CardContent className="p-4">
+                <div className="flex items-center gap-3">
+                  {integrationStatus?.paypal?.configured ? (
+                    <CheckCircle className="w-8 h-8 text-emerald-400" />
+                  ) : (
+                    <XCircle className="w-8 h-8 text-yellow-400" />
+                  )}
+                  <div>
+                    <p className="font-medium text-white">PayPal Subscriptions</p>
+                    <p className="text-xs text-zinc-500">
+                      {integrationStatus?.paypal?.configured ? 'Configured' : 'Not configured'}
+                      {integrationStatus?.paypal?.mode ? ` • ${integrationStatus.paypal.mode.toUpperCase()}` : ''}
+                    </p>
+                  </div>
+                </div>
+              </CardContent>
+            </Card>
@@
-        <TabsContent value="subscriptions" className="space-y-6 mt-6">
+        <TabsContent value="subscriptions" className="space-y-6 mt-6">
+          <Card className={`glass-card border-l-4 ${integrationStatus?.paypal?.configured ? 'border-emerald-500' : 'border-yellow-500'}`}>
+            <CardHeader>
+              <CardTitle className="text-lg flex items-center gap-2">
+                <DollarSign className="w-5 h-5 text-cyan-400" />
+                PayPal Subscription Automation
+              </CardTitle>
+              <CardDescription>Access activation/deactivation via PayPal Express Checkout + IPN</CardDescription>
+            </CardHeader>
+            <CardContent className="flex items-center justify-between">
+              <div className="flex items-center gap-3">
+                {integrationStatus?.paypal?.configured ? (
+                  <CheckCircle className="w-6 h-6 text-emerald-400" />
+                ) : (
+                  <XCircle className="w-6 h-6 text-yellow-400" />
+                )}
+                <div>
+                  <p className="text-sm font-medium text-white">
+                    {integrationStatus?.paypal?.configured ? 'PayPal is configured' : 'PayPal is not configured'}
+                  </p>
+                  <p className="text-xs text-zinc-500">
+                    Mode: {integrationStatus?.paypal?.mode ? integrationStatus.paypal.mode.toUpperCase() : 'SANDBOX'}
+                  </p>
+                </div>
+              </div>
+              <Badge variant="secondary">
+                Configure in Integrations tab
+              </Badge>
+            </CardContent>
+          </Card>
@@
           <div className="flex justify-end">
             <Button onClick={saveIntegrationSettings} className="bg-emerald-600 hover:bg-emerald-700" disabled={savingIntegration}>
@@
           </div>
+
+          <Card className="glass-card">
+            <CardHeader>
+              <CardTitle className="text-lg flex items-center gap-2">
+                <DollarSign className="w-5 h-5 text-cyan-400" />
+                PayPal Configuration
+              </CardTitle>
+              <CardDescription>Configure PayPal (NVP) credentials for subscription activation/deactivation via IPN</CardDescription>
+            </CardHeader>
+            <CardContent className="space-y-4">
+              <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-800/30 border border-zinc-700/30">
+                <div>
+                  <p className="text-sm font-medium text-white">Enable PayPal</p>
+                  <p className="text-xs text-zinc-500">If disabled, PayPal checkout will be blocked</p>
+                </div>
+                <Switch
+                  checked={!!integrationSettings.paypal_enabled}
+                  onCheckedChange={(v) => setIntegrationSettings(s => ({ ...s, paypal_enabled: v }))}
+                />
+              </div>
+
+              <div className="space-y-2">
+                <Label>Mode</Label>
+                <div className="flex items-center gap-2">
+                  <Button
+                    type="button"
+                    variant={integrationSettings.paypal_mode === 'sandbox' ? 'default' : 'outline'}
+                    onClick={() => setIntegrationSettings(s => ({ ...s, paypal_mode: 'sandbox' }))}
+                  >
+                    Sandbox
+                  </Button>
+                  <Button
+                    type="button"
+                    variant={integrationSettings.paypal_mode === 'live' ? 'default' : 'outline'}
+                    onClick={() => setIntegrationSettings(s => ({ ...s, paypal_mode: 'live' }))}
+                  >
+                    Live
+                  </Button>
+                  <Badge variant="secondary" className="ml-auto">
+                    {integrationStatus?.paypal?.mode ? integrationStatus.paypal.mode.toUpperCase() : 'SANDBOX'}
+                  </Badge>
+                </div>
+                <p className="text-xs text-zinc-500">
+                  Use Sandbox for testing. Switch to Live only after end-to-end tests succeed.
+                </p>
+              </div>
+
+              <div className="space-y-2">
+                <Label>API Username</Label>
+                <Input
+                  value={integrationSettings.paypal_api_username}
+                  onChange={(e) => setIntegrationSettings(s => ({ ...s, paypal_api_username: e.target.value }))}
+                  placeholder={integrationStatus?.paypal?.api_username_masked ? `Stored: ${integrationStatus.paypal.api_username_masked}` : "Your PayPal API username"}
+                />
+              </div>
+
+              <PasswordInput
+                label="API Password"
+                value={integrationSettings.paypal_api_password}
+                onChange={(v) => setIntegrationSettings(s => ({ ...s, paypal_api_password: v }))}
+                show={showPayPalPassword}
+                onToggle={() => setShowPayPalPassword(!showPayPalPassword)}
+                placeholder={integrationStatus?.paypal?.has_api_password ? "Leave blank to keep existing" : "Your PayPal API password"}
+              />
+
+              <PasswordInput
+                label="API Signature"
+                value={integrationSettings.paypal_api_signature}
+                onChange={(v) => setIntegrationSettings(s => ({ ...s, paypal_api_signature: v }))}
+                show={showPayPalSignature}
+                onToggle={() => setShowPayPalSignature(!showPayPalSignature)}
+                placeholder={integrationStatus?.paypal?.has_api_signature ? "Leave blank to keep existing" : "Your PayPal API signature"}
+              />
+
+              <p className="text-xs text-zinc-500">
+                Tip: If you only want to switch mode (Sandbox/Live), leave password/signature empty to retain stored secrets.
+              </p>
+            </CardContent>
+          </Card>
