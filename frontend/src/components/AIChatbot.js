import { useState, useEffect, useRef } from 'react';
import { MessageCircle, X, Send, Bot, User, Sparkles, ChevronDown } from 'lucide-react';
import { Button } from './ui/button';
import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

// Quick action buttons for common questions
const QUICK_ACTIONS = [
  { label: '💰 Pricing', topic: 'pricing' },
  { label: '🚀 Features', topic: 'features' },
  { label: '📈 What is Covered Call?', topic: 'covered_call' },
  { label: '🎯 What is PMCC?', topic: 'pmcc' },
  { label: '🆓 Free Trial', topic: 'trial' },
];

const AIChatbot = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [showWelcome, setShowWelcome] = useState(false);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Show welcome popup after 3 seconds
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!isOpen) {
        setShowWelcome(true);
      }
    }, 3000);

    return () => clearTimeout(timer);
  }, []);

  // Generate session ID on mount
  useEffect(() => {
    const storedSessionId = localStorage.getItem('chatbot_session_id');
    if (storedSessionId) {
      setSessionId(storedSessionId);
    } else {
      const newSessionId = `chat_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      setSessionId(newSessionId);
      localStorage.setItem('chatbot_session_id', newSessionId);
    }
  }, []);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when chat opens
  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
    }
  }, [isOpen]);

  const openChat = () => {
    setIsOpen(true);
    setShowWelcome(false);
    
    // Add welcome message if no messages yet
    if (messages.length === 0) {
      setMessages([
        {
          role: 'assistant',
          content: "👋 Hi there! I'm your Covered Call Engine assistant.\n\nI can help you:\n• Learn about covered calls & PMCC strategies\n• Explore our platform features\n• Get started with your FREE 7-day trial\n\nWhat would you like to know?",
          timestamp: new Date()
        }
      ]);
    }
  };

  const sendMessage = async (text) => {
    if (!text.trim() || isLoading) return;

    const userMessage = {
      role: 'user',
      content: text.trim(),
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);

    try {
      const response = await axios.post(`${BACKEND_URL}/api/chatbot/message`, null, {
        params: {
          message: text.trim(),
          session_id: sessionId
        }
      });

      const assistantMessage = {
        role: 'assistant',
        content: response.data.response,
        timestamp: new Date()
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Chatbot error:', error);
      const errorMessage = {
        role: 'assistant',
        content: "I apologize, but I'm having trouble responding right now. Please try again or start your FREE trial to explore the platform directly!",
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleQuickAction = async (topic) => {
    try {
      const response = await axios.get(`${BACKEND_URL}/api/chatbot/quick-response/${topic}`);
      
      if (response.data.response) {
        const userMessage = {
          role: 'user',
          content: QUICK_ACTIONS.find(a => a.topic === topic)?.label || topic,
          timestamp: new Date()
        };
        
        const assistantMessage = {
          role: 'assistant',
          content: response.data.response,
          timestamp: new Date()
        };

        setMessages(prev => [...prev, userMessage, assistantMessage]);
      }
    } catch (error) {
      // Fallback to regular message
      sendMessage(QUICK_ACTIONS.find(a => a.topic === topic)?.label || topic);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputValue);
    }
  };

  const formatMessage = (content) => {
    // Convert markdown-style formatting to HTML
    return content
      .split('\n')
      .map((line, i) => {
        // Bold text
        line = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // Bullet points
        if (line.startsWith('• ') || line.startsWith('- ')) {
          return `<li key=${i} class="ml-4">${line.substring(2)}</li>`;
        }
        // Numbered lists
        if (/^\d+\.\s/.test(line)) {
          return `<li key=${i} class="ml-4">${line.substring(line.indexOf(' ') + 1)}</li>`;
        }
        return line;
      })
      .join('<br/>');
  };

  return (
    <>
      {/* Welcome Popup */}
      {showWelcome && !isOpen && (
        <div className="fixed bottom-24 right-6 z-50 animate-bounce-in">
          <div className="bg-gradient-to-r from-violet-600 to-emerald-600 p-[1px] rounded-2xl shadow-2xl">
            <div className="bg-zinc-900 rounded-2xl p-4 w-64">
              <button 
                onClick={() => setShowWelcome(false)}
                className="absolute -top-2 -right-2 bg-zinc-800 rounded-full p-1 hover:bg-zinc-700 transition-colors"
              >
                <X className="w-4 h-4 text-zinc-400" />
              </button>
              <div className="flex flex-col items-center text-center">
                <div className="w-12 h-12 rounded-full bg-gradient-to-r from-violet-500 to-emerald-500 flex items-center justify-center mb-3">
                  <Bot className="w-6 h-6 text-white" />
                </div>
                <p className="text-white text-sm font-medium mb-1">
                  👋 Need help finding covered calls?
                </p>
                <p className="text-zinc-400 text-xs mb-4">
                  I can answer your questions and help you get started!
                </p>
                <Button 
                  onClick={openChat}
                  size="sm"
                  className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs w-full"
                >
                  <Sparkles className="w-3 h-3 mr-1" />
                  Chat with AI Assistant
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Chat Button */}
      <button
        onClick={isOpen ? () => setIsOpen(false) : openChat}
        className={`fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full shadow-2xl flex items-center justify-center transition-all duration-300 ${
          isOpen 
            ? 'bg-zinc-800 hover:bg-zinc-700' 
            : 'bg-gradient-to-r from-violet-600 to-emerald-600 hover:from-violet-500 hover:to-emerald-500 animate-pulse-slow'
        }`}
      >
        {isOpen ? (
          <ChevronDown className="w-6 h-6 text-white" />
        ) : (
          <MessageCircle className="w-6 h-6 text-white" />
        )}
      </button>

      {/* Chat Window */}
      {isOpen && (
        <div className="fixed bottom-24 right-6 z-50 w-96 h-[500px] bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-800 flex flex-col overflow-hidden animate-slide-up">
          {/* Header */}
          <div className="bg-gradient-to-r from-violet-600/20 to-emerald-600/20 border-b border-zinc-800 p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-gradient-to-r from-violet-500 to-emerald-500 flex items-center justify-center">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="text-white font-semibold">AI Assistant</h3>
                <p className="text-emerald-400 text-xs flex items-center gap-1">
                  <span className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></span>
                  Online - Ready to help
                </p>
              </div>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((msg, index) => (
              <div
                key={index}
                className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
              >
                <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                  msg.role === 'user' 
                    ? 'bg-violet-600' 
                    : 'bg-gradient-to-r from-violet-500 to-emerald-500'
                }`}>
                  {msg.role === 'user' ? (
                    <User className="w-4 h-4 text-white" />
                  ) : (
                    <Bot className="w-4 h-4 text-white" />
                  )}
                </div>
                <div className={`max-w-[75%] rounded-2xl px-4 py-2 ${
                  msg.role === 'user'
                    ? 'bg-violet-600 text-white rounded-tr-sm'
                    : 'bg-zinc-800 text-zinc-100 rounded-tl-sm'
                }`}>
                  <div 
                    className="text-sm leading-relaxed"
                    dangerouslySetInnerHTML={{ __html: formatMessage(msg.content) }}
                  />
                </div>
              </div>
            ))}
            
            {isLoading && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-gradient-to-r from-violet-500 to-emerald-500 flex items-center justify-center">
                  <Bot className="w-4 h-4 text-white" />
                </div>
                <div className="bg-zinc-800 rounded-2xl rounded-tl-sm px-4 py-3">
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                    <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                    <span className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
                  </div>
                </div>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </div>

          {/* Quick Actions */}
          {messages.length <= 1 && (
            <div className="px-4 pb-2">
              <div className="flex flex-wrap gap-2">
                {QUICK_ACTIONS.map((action) => (
                  <button
                    key={action.topic}
                    onClick={() => handleQuickAction(action.topic)}
                    className="text-xs px-3 py-1.5 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white transition-colors border border-zinc-700"
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Input */}
          <div className="p-4 border-t border-zinc-800">
            <div className="flex gap-2">
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Type your question..."
                className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2 text-white text-sm placeholder-zinc-500 focus:outline-none focus:border-violet-500 transition-colors"
                disabled={isLoading}
              />
              <button
                onClick={() => sendMessage(inputValue)}
                disabled={!inputValue.trim() || isLoading}
                className="w-10 h-10 rounded-xl bg-gradient-to-r from-violet-600 to-emerald-600 hover:from-violet-500 hover:to-emerald-500 flex items-center justify-center transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Send className="w-4 h-4 text-white" />
              </button>
            </div>
            <p className="text-center text-zinc-600 text-xs mt-2">
              Powered by AI • <a href="/pricing" className="text-emerald-500 hover:underline">Start FREE Trial</a>
            </p>
          </div>
        </div>
      )}

      {/* Custom animations */}
      <style jsx>{`
        @keyframes bounce-in {
          0% { transform: scale(0.3); opacity: 0; }
          50% { transform: scale(1.05); }
          70% { transform: scale(0.9); }
          100% { transform: scale(1); opacity: 1; }
        }
        @keyframes slide-up {
          0% { transform: translateY(20px); opacity: 0; }
          100% { transform: translateY(0); opacity: 1; }
        }
        @keyframes pulse-slow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.4); }
          50% { box-shadow: 0 0 0 10px rgba(139, 92, 246, 0); }
        }
        .animate-bounce-in { animation: bounce-in 0.5s ease-out; }
        .animate-slide-up { animation: slide-up 0.3s ease-out; }
        .animate-pulse-slow { animation: pulse-slow 2s infinite; }
      `}</style>
    </>
  );
};

export default AIChatbot;
