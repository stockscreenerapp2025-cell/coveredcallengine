/**
 * AdminSupport - Support Ticket Management Component
 * Phase 1: Human-in-the-loop - All AI responses require admin approval before sending
 */
import { useState, useEffect, useCallback } from 'react';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Skeleton } from '../components/ui/skeleton';
import { Switch } from '../components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import {
  MessageSquare,
  Search,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Clock,
  AlertCircle,
  CheckCircle,
  XCircle,
  Send,
  Edit3,
  BookOpen,
  Plus,
  Trash2,
  ArrowUp,
  ArrowRight,
  Eye,
  Sparkles,
  User,
  Mail,
  AlertTriangle,
  ThumbsUp,
  ThumbsDown,
  RotateCw,
  Zap,
  Settings
} from 'lucide-react';
import { toast } from 'sonner';

// Status badge styling
const getStatusBadge = (status) => {
  const styles = {
    'new': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    'ai_drafted': 'bg-violet-500/20 text-violet-400 border-violet-500/30',
    'awaiting_human_review': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    'awaiting_user': 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    'escalated': 'bg-red-500/20 text-red-400 border-red-500/30',
    'resolved': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    'closed': 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
  };
  return <Badge className={styles[status] || styles['new']}>{status?.replace(/_/g, ' ')}</Badge>;
};

// Priority badge styling
const getPriorityBadge = (priority) => {
  const styles = {
    'urgent': 'bg-red-500/20 text-red-400',
    'high': 'bg-orange-500/20 text-orange-400',
    'normal': 'bg-zinc-500/20 text-zinc-400',
    'low': 'bg-zinc-700/20 text-zinc-500',
  };
  return <Badge className={styles[priority] || styles['normal']}>{priority}</Badge>;
};

// Sentiment indicator
const getSentimentIcon = (sentiment) => {
  if (sentiment === 'positive') return <ThumbsUp className="w-4 h-4 text-emerald-400" />;
  if (sentiment === 'negative') return <ThumbsDown className="w-4 h-4 text-red-400" />;
  return <ArrowRight className="w-4 h-4 text-zinc-400" />;
};

// Confidence score indicator
const ConfidenceScore = ({ score }) => {
  let color = 'text-red-400';
  if (score >= 80) color = 'text-emerald-400';
  else if (score >= 60) color = 'text-yellow-400';
  else if (score >= 40) color = 'text-orange-400';
  
  return (
    <span className={`text-xs font-mono ${color}`}>
      {score}%
    </span>
  );
};

const AdminSupport = () => {
  const [activeSubTab, setActiveSubTab] = useState('tickets');
  
  // Tickets state
  const [tickets, setTickets] = useState([]);
  const [ticketsLoading, setTicketsLoading] = useState(false);
  const [ticketsPagination, setTicketsPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [ticketFilters, setTicketFilters] = useState({ status: '', category: '', priority: '', search: '' });
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [ticketDetailLoading, setTicketDetailLoading] = useState(false);
  
  // Reply state
  const [replyMessage, setReplyMessage] = useState('');
  const [sendingReply, setSendingReply] = useState(false);
  const [editingDraft, setEditingDraft] = useState(false);
  const [editedDraft, setEditedDraft] = useState('');
  
  // Stats state
  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(false);
  
  // Knowledge Base state
  const [kbArticles, setKbArticles] = useState([]);
  const [kbLoading, setKbLoading] = useState(false);
  const [kbPagination, setKbPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [kbSearch, setKbSearch] = useState('');
  const [showKbForm, setShowKbForm] = useState(false);
  const [kbForm, setKbForm] = useState({ question: '', answer: '', category: 'general', active: true });
  const [editingKbId, setEditingKbId] = useState(null);
  
  // Auto-response settings state
  const [autoResponseSettings, setAutoResponseSettings] = useState({
    enabled: false,
    delay_minutes: 60,
    min_confidence: 85,
    allowed_categories: ['general', 'how_it_works', 'educational']
  });
  const [savingAutoResponse, setSavingAutoResponse] = useState(false);

  // Fetch tickets
  const fetchTickets = useCallback(async (page = 1) => {
    setTicketsLoading(true);
    try {
      const params = new URLSearchParams({ page: page.toString(), limit: '20' });
      if (ticketFilters.status && ticketFilters.status !== 'all') params.append('status', ticketFilters.status);
      if (ticketFilters.category && ticketFilters.category !== 'all') params.append('category', ticketFilters.category);
      if (ticketFilters.priority && ticketFilters.priority !== 'all') params.append('priority', ticketFilters.priority);
      if (ticketFilters.search) params.append('search', ticketFilters.search);
      
      const response = await api.get(`/support/admin/tickets?${params.toString()}`);
      setTickets(response.data.tickets || []);
      setTicketsPagination({
        page: response.data.page,
        pages: response.data.pages,
        total: response.data.total
      });
    } catch (error) {
      console.error('Tickets fetch error:', error);
      toast.error('Failed to load tickets');
    } finally {
      setTicketsLoading(false);
    }
  }, [ticketFilters]);

  // Fetch single ticket detail
  const fetchTicketDetail = async (ticketId) => {
    setTicketDetailLoading(true);
    try {
      const response = await api.get(`/support/admin/tickets/${ticketId}`);
      setSelectedTicket(response.data);
      setEditedDraft(response.data.ai_draft_response || '');
    } catch (error) {
      console.error('Ticket detail error:', error);
      toast.error('Failed to load ticket details');
    } finally {
      setTicketDetailLoading(false);
    }
  };

  // Fetch stats
  const fetchStats = async () => {
    setStatsLoading(true);
    try {
      const response = await api.get('/support/admin/stats');
      setStats(response.data);
    } catch (error) {
      console.error('Stats error:', error);
    } finally {
      setStatsLoading(false);
    }
  };

  // Fetch KB articles
  const fetchKbArticles = async (page = 1) => {
    setKbLoading(true);
    try {
      const params = new URLSearchParams({ page: page.toString(), limit: '20' });
      if (kbSearch) params.append('search', kbSearch);
      
      const response = await api.get(`/support/admin/kb?${params.toString()}`);
      setKbArticles(response.data.articles || []);
      setKbPagination({
        page: response.data.page,
        pages: response.data.pages,
        total: response.data.total
      });
    } catch (error) {
      console.error('KB fetch error:', error);
    } finally {
      setKbLoading(false);
    }
  };
  
  // Fetch auto-response settings
  const fetchAutoResponseSettings = async () => {
    try {
      const response = await api.get('/support/admin/auto-response-settings');
      setAutoResponseSettings(response.data);
    } catch (error) {
      console.error('Auto-response settings error:', error);
    }
  };
  
  // Save auto-response settings
  const handleSaveAutoResponseSettings = async () => {
    setSavingAutoResponse(true);
    try {
      const params = new URLSearchParams({
        enabled: autoResponseSettings.enabled.toString(),
        delay_minutes: autoResponseSettings.delay_minutes.toString(),
        min_confidence: autoResponseSettings.min_confidence.toString(),
        allowed_categories: autoResponseSettings.allowed_categories.join(',')
      });
      await api.put(`/support/admin/auto-response-settings?${params.toString()}`);
      toast.success('Auto-response settings saved');
    } catch (error) {
      toast.error('Failed to save settings');
    } finally {
      setSavingAutoResponse(false);
    }
  };

  useEffect(() => {
    fetchTickets(1);
    fetchStats();
    fetchAutoResponseSettings();
  }, []);

  // Send admin reply
  const handleSendReply = async () => {
    if (!replyMessage.trim() || !selectedTicket) return;
    
    setSendingReply(true);
    try {
      await api.post(`/support/admin/tickets/${selectedTicket.id}/reply`, null, {
        params: { message: replyMessage, send_email: true }
      });
      toast.success('Reply sent to user');
      setReplyMessage('');
      fetchTicketDetail(selectedTicket.id);
      fetchTickets(ticketsPagination.page);
    } catch (error) {
      toast.error('Failed to send reply');
    } finally {
      setSendingReply(false);
    }
  };

  // Approve AI draft
  const handleApproveDraft = async (edit = false) => {
    if (!selectedTicket) return;
    
    setSendingReply(true);
    try {
      const params = { send_email: true };
      if (edit && editedDraft !== selectedTicket.ai_draft_response) {
        params.edit_message = editedDraft;
      }
      
      await api.post(`/support/admin/tickets/${selectedTicket.id}/approve-draft`, null, { params });
      toast.success(edit ? 'Edited response sent to user' : 'AI draft approved and sent');
      setEditingDraft(false);
      fetchTicketDetail(selectedTicket.id);
      fetchTickets(ticketsPagination.page);
    } catch (error) {
      toast.error('Failed to send response');
    } finally {
      setSendingReply(false);
    }
  };

  // Regenerate AI draft
  const handleRegenerateDraft = async () => {
    if (!selectedTicket) return;
    
    try {
      const response = await api.post(`/support/admin/tickets/${selectedTicket.id}/regenerate-draft`);
      toast.success('AI draft regenerated');
      setEditedDraft(response.data.draft);
      fetchTicketDetail(selectedTicket.id);
    } catch (error) {
      toast.error('Failed to regenerate draft');
    }
  };

  // Update ticket status
  const handleStatusChange = async (newStatus) => {
    if (!selectedTicket) return;
    
    try {
      await api.put(`/support/admin/tickets/${selectedTicket.id}`, null, {
        params: { status: newStatus }
      });
      toast.success('Status updated');
      fetchTicketDetail(selectedTicket.id);
      fetchTickets(ticketsPagination.page);
    } catch (error) {
      toast.error('Failed to update status');
    }
  };

  // Escalate ticket
  const handleEscalate = async () => {
    const reason = prompt('Enter escalation reason:');
    if (!reason || !selectedTicket) return;
    
    try {
      await api.post(`/support/admin/tickets/${selectedTicket.id}/escalate`, null, {
        params: { reason }
      });
      toast.success('Ticket escalated');
      fetchTicketDetail(selectedTicket.id);
      fetchTickets(ticketsPagination.page);
    } catch (error) {
      toast.error('Failed to escalate ticket');
    }
  };

  // KB CRUD operations
  const handleSaveKbArticle = async () => {
    if (!kbForm.question || !kbForm.answer) {
      toast.error('Please fill in question and answer');
      return;
    }
    
    try {
      if (editingKbId) {
        await api.put(`/support/admin/kb/${editingKbId}`, null, {
          params: kbForm
        });
        toast.success('Article updated');
      } else {
        await api.post('/support/admin/kb', kbForm);
        toast.success('Article created');
      }
      setShowKbForm(false);
      setKbForm({ question: '', answer: '', category: 'general', active: true });
      setEditingKbId(null);
      fetchKbArticles();
    } catch (error) {
      toast.error('Failed to save article');
    }
  };

  const handleDeleteKbArticle = async (articleId) => {
    if (!window.confirm('Are you sure you want to delete this article?')) return;
    
    try {
      await api.delete(`/support/admin/kb/${articleId}`);
      toast.success('Article deleted');
      fetchKbArticles();
    } catch (error) {
      toast.error('Failed to delete article');
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-support-section">
      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {statsLoading ? (
          [...Array(4)].map((_, i) => <Skeleton key={i} className="h-24 rounded-lg" />)
        ) : (
          <>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-blue-500/20">
                    <MessageSquare className="w-5 h-5 text-blue-400" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{stats?.total_tickets || 0}</div>
                    <div className="text-xs text-zinc-500">Total Tickets</div>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-yellow-500/20">
                    <Clock className="w-5 h-5 text-yellow-400" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{stats?.awaiting_review || 0}</div>
                    <div className="text-xs text-zinc-500">Awaiting Review</div>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-red-500/20">
                    <AlertTriangle className="w-5 h-5 text-red-400" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{stats?.open_tickets || 0}</div>
                    <div className="text-xs text-zinc-500">Open</div>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="glass-card">
              <CardContent className="p-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-emerald-500/20">
                    <CheckCircle className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{stats?.resolved_today || 0}</div>
                    <div className="text-xs text-zinc-500">Resolved Today</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {/* Sub-tabs */}
      <Tabs value={activeSubTab} onValueChange={setActiveSubTab} className="w-full">
        <TabsList className="bg-zinc-800/50 p-1">
          <TabsTrigger value="tickets" className="flex items-center gap-2" onClick={() => fetchTickets(1)}>
            <MessageSquare className="w-4 h-4" />
            Tickets
          </TabsTrigger>
          <TabsTrigger value="knowledge-base" className="flex items-center gap-2" onClick={() => fetchKbArticles(1)}>
            <BookOpen className="w-4 h-4" />
            Knowledge Base
          </TabsTrigger>
          <TabsTrigger value="settings" className="flex items-center gap-2" onClick={() => fetchAutoResponseSettings()}>
            <Zap className="w-4 h-4" />
            Auto-Response
          </TabsTrigger>
        </TabsList>

        {/* Tickets Tab */}
        <TabsContent value="tickets" className="mt-4 space-y-4">
          {/* Filters */}
          <Card className="glass-card">
            <CardContent className="p-4">
              <div className="flex flex-wrap gap-3 items-center">
                <div className="relative flex-1 min-w-[200px]">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                  <Input
                    placeholder="Search tickets..."
                    value={ticketFilters.search}
                    onChange={(e) => setTicketFilters(f => ({ ...f, search: e.target.value }))}
                    className="input-dark pl-9"
                    data-testid="ticket-search-input"
                  />
                </div>
                <Select value={ticketFilters.status} onValueChange={(v) => setTicketFilters(f => ({ ...f, status: v }))}>
                  <SelectTrigger className="w-36 bg-zinc-800 border-zinc-700">
                    <SelectValue placeholder="Status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Status</SelectItem>
                    <SelectItem value="new">New</SelectItem>
                    <SelectItem value="ai_drafted">AI Drafted</SelectItem>
                    <SelectItem value="awaiting_human_review">Awaiting Review</SelectItem>
                    <SelectItem value="awaiting_user">Awaiting User</SelectItem>
                    <SelectItem value="escalated">Escalated</SelectItem>
                    <SelectItem value="resolved">Resolved</SelectItem>
                    <SelectItem value="closed">Closed</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={ticketFilters.priority} onValueChange={(v) => setTicketFilters(f => ({ ...f, priority: v }))}>
                  <SelectTrigger className="w-32 bg-zinc-800 border-zinc-700">
                    <SelectValue placeholder="Priority" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Priority</SelectItem>
                    <SelectItem value="urgent">Urgent</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                    <SelectItem value="normal">Normal</SelectItem>
                    <SelectItem value="low">Low</SelectItem>
                  </SelectContent>
                </Select>
                <Button onClick={() => fetchTickets(1)} className="bg-violet-600 hover:bg-violet-700">
                  <Search className="w-4 h-4 mr-2" />
                  Search
                </Button>
                <Button onClick={() => { fetchTickets(1); fetchStats(); }} variant="outline" className="btn-outline">
                  <RefreshCw className="w-4 h-4" />
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Tickets List */}
          <div className="grid md:grid-cols-2 gap-4">
            {/* Left: Ticket List */}
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-violet-400" />
                  Support Tickets
                  <Badge className="bg-zinc-700 text-zinc-300 ml-2">{ticketsPagination.total}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="p-2">
                {ticketsLoading ? (
                  <div className="space-y-2">
                    {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
                  </div>
                ) : tickets.length === 0 ? (
                  <div className="text-center py-12 text-zinc-500">
                    <MessageSquare className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>No tickets found</p>
                  </div>
                ) : (
                  <div className="space-y-2 max-h-[600px] overflow-y-auto">
                    {tickets.map((ticket) => (
                      <div
                        key={ticket.id}
                        onClick={() => fetchTicketDetail(ticket.id)}
                        className={`p-3 rounded-lg border cursor-pointer transition-all ${
                          selectedTicket?.id === ticket.id
                            ? 'bg-violet-500/10 border-violet-500/50'
                            : 'bg-zinc-800/50 border-zinc-700 hover:border-zinc-600'
                        }`}
                        data-testid={`ticket-item-${ticket.ticket_number}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-mono text-violet-400">{ticket.ticket_number}</span>
                              {getSentimentIcon(ticket.sentiment)}
                              {ticket.ai_confidence_score && (
                                <ConfidenceScore score={ticket.ai_confidence_score} />
                              )}
                            </div>
                            <p className="text-sm text-white font-medium truncate">{ticket.subject}</p>
                            <p className="text-xs text-zinc-500 truncate">{ticket.user_email}</p>
                          </div>
                          <div className="flex flex-col items-end gap-1">
                            {getStatusBadge(ticket.status)}
                            {getPriorityBadge(ticket.priority)}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 mt-2 text-xs text-zinc-500">
                          <Clock className="w-3 h-3" />
                          {new Date(ticket.created_at).toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                
                {/* Pagination */}
                {ticketsPagination.pages > 1 && (
                  <div className="flex items-center justify-between pt-4 border-t border-zinc-800 mt-4">
                    <span className="text-sm text-zinc-500">
                      Page {ticketsPagination.page} of {ticketsPagination.pages}
                    </span>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fetchTickets(ticketsPagination.page - 1)}
                        disabled={ticketsPagination.page <= 1}
                      >
                        <ChevronLeft className="w-4 h-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fetchTickets(ticketsPagination.page + 1)}
                        disabled={ticketsPagination.page >= ticketsPagination.pages}
                      >
                        <ChevronRight className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Right: Ticket Detail */}
            <Card className="glass-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Eye className="w-5 h-5 text-emerald-400" />
                  Ticket Detail
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4">
                {ticketDetailLoading ? (
                  <div className="space-y-4">
                    <Skeleton className="h-8 w-32" />
                    <Skeleton className="h-20" />
                    <Skeleton className="h-40" />
                  </div>
                ) : !selectedTicket ? (
                  <div className="text-center py-12 text-zinc-500">
                    <Eye className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>Select a ticket to view details</p>
                  </div>
                ) : (
                  <div className="space-y-4 max-h-[600px] overflow-y-auto">
                    {/* Header */}
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-lg font-mono text-violet-400">{selectedTicket.ticket_number}</span>
                          {getStatusBadge(selectedTicket.status)}
                        </div>
                        <h3 className="text-xl text-white font-semibold">{selectedTicket.subject}</h3>
                      </div>
                      <div className="flex gap-2">
                        {selectedTicket.status !== 'resolved' && selectedTicket.status !== 'closed' && (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleStatusChange('resolved')}
                              className="text-emerald-400 hover:text-emerald-300"
                            >
                              <CheckCircle className="w-4 h-4 mr-1" />
                              Resolve
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={handleEscalate}
                              className="text-red-400 hover:text-red-300"
                            >
                              <ArrowUp className="w-4 h-4 mr-1" />
                              Escalate
                            </Button>
                          </>
                        )}
                      </div>
                    </div>

                    {/* User Info */}
                    <div className="p-3 rounded-lg bg-zinc-800/50 border border-zinc-700">
                      <div className="flex items-center gap-3">
                        <div className="p-2 rounded-full bg-zinc-700">
                          <User className="w-5 h-5 text-zinc-400" />
                        </div>
                        <div>
                          <p className="text-white font-medium">{selectedTicket.user_name}</p>
                          <p className="text-sm text-zinc-400">{selectedTicket.user_email}</p>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2 mt-3">
                        <Badge className="bg-zinc-700/50">{selectedTicket.category?.replace(/_/g, ' ')}</Badge>
                        {getPriorityBadge(selectedTicket.priority)}
                        <div className="flex items-center gap-1">
                          {getSentimentIcon(selectedTicket.sentiment)}
                          <span className="text-xs text-zinc-500">{selectedTicket.sentiment}</span>
                        </div>
                        {selectedTicket.ai_draft_confidence && (
                          <div className="flex items-center gap-1">
                            <Sparkles className="w-3 h-3 text-violet-400" />
                            <ConfidenceScore score={selectedTicket.ai_draft_confidence} />
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Conversation Thread */}
                    <div className="space-y-3">
                      <h4 className="text-sm font-medium text-zinc-400">Conversation</h4>
                      {selectedTicket.messages?.map((msg, idx) => (
                        <div
                          key={msg.id || idx}
                          className={`p-3 rounded-lg ${
                            msg.sender_type === 'user'
                              ? 'bg-zinc-800/50 border border-zinc-700'
                              : msg.sender_type === 'admin'
                              ? 'bg-emerald-500/10 border border-emerald-500/30'
                              : 'bg-violet-500/10 border border-violet-500/30'
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-2">
                            {msg.sender_type === 'user' ? (
                              <User className="w-4 h-4 text-zinc-400" />
                            ) : msg.sender_type === 'admin' ? (
                              <CheckCircle className="w-4 h-4 text-emerald-400" />
                            ) : (
                              <Sparkles className="w-4 h-4 text-violet-400" />
                            )}
                            <span className="text-sm font-medium text-white">{msg.sender_name}</span>
                            <span className="text-xs text-zinc-500">
                              {new Date(msg.created_at).toLocaleString()}
                            </span>
                            {msg.sent_via_email && (
                              <Badge className="bg-cyan-500/20 text-cyan-400 text-xs">Email Sent</Badge>
                            )}
                          </div>
                          <p className="text-sm text-zinc-300 whitespace-pre-wrap">{msg.content}</p>
                        </div>
                      ))}
                    </div>

                    {/* AI Draft Section (Phase 1 - Human in the loop) */}
                    {selectedTicket.ai_draft_response && 
                     selectedTicket.status !== 'resolved' && 
                     selectedTicket.status !== 'closed' && (
                      <div className="p-4 rounded-lg bg-violet-500/10 border border-violet-500/30">
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-2">
                            <Sparkles className="w-5 h-5 text-violet-400" />
                            <span className="text-sm font-medium text-violet-300">AI Draft Response</span>
                            <ConfidenceScore score={selectedTicket.ai_draft_confidence || 0} />
                          </div>
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={handleRegenerateDraft}
                              className="text-violet-400 hover:text-violet-300"
                            >
                              <RotateCw className="w-4 h-4 mr-1" />
                              Regenerate
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setEditingDraft(!editingDraft);
                                setEditedDraft(selectedTicket.ai_draft_response);
                              }}
                              className="text-zinc-400 hover:text-white"
                            >
                              <Edit3 className="w-4 h-4 mr-1" />
                              {editingDraft ? 'Cancel' : 'Edit'}
                            </Button>
                          </div>
                        </div>
                        
                        {editingDraft ? (
                          <textarea
                            value={editedDraft}
                            onChange={(e) => setEditedDraft(e.target.value)}
                            className="w-full h-40 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700 text-white text-sm resize-none focus:outline-none focus:border-violet-500"
                            data-testid="draft-edit-textarea"
                          />
                        ) : (
                          <p className="text-sm text-zinc-300 whitespace-pre-wrap bg-zinc-900/50 p-3 rounded">
                            {selectedTicket.ai_draft_response}
                          </p>
                        )}
                        
                        <div className="flex gap-2 mt-3">
                          <Button
                            onClick={() => handleApproveDraft(editingDraft)}
                            disabled={sendingReply}
                            className="bg-emerald-600 hover:bg-emerald-700 flex-1"
                            data-testid="approve-draft-btn"
                          >
                            {sendingReply ? (
                              <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                            ) : (
                              <Send className="w-4 h-4 mr-2" />
                            )}
                            {editingDraft ? 'Send Edited Response' : 'Approve & Send'}
                          </Button>
                        </div>
                        <p className="text-xs text-zinc-500 mt-2">
                          ⚠️ Phase 1: All responses are reviewed before sending. Click to approve and email the user.
                        </p>
                      </div>
                    )}

                    {/* Manual Reply */}
                    {selectedTicket.status !== 'resolved' && selectedTicket.status !== 'closed' && (
                      <div className="pt-4 border-t border-zinc-800">
                        <Label className="text-zinc-400 text-sm">Custom Reply</Label>
                        <textarea
                          value={replyMessage}
                          onChange={(e) => setReplyMessage(e.target.value)}
                          className="w-full h-24 mt-2 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700 text-white text-sm resize-none focus:outline-none focus:border-emerald-500"
                          placeholder="Write a custom response..."
                          data-testid="custom-reply-textarea"
                        />
                        <Button
                          onClick={handleSendReply}
                          disabled={sendingReply || !replyMessage.trim()}
                          className="w-full mt-2 bg-emerald-600 hover:bg-emerald-700"
                          data-testid="send-reply-btn"
                        >
                          {sendingReply ? (
                            <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                          ) : (
                            <Send className="w-4 h-4 mr-2" />
                          )}
                          Send Reply & Email User
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Knowledge Base Tab */}
        <TabsContent value="knowledge-base" className="mt-4">
          <Card className="glass-card">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <BookOpen className="w-5 h-5 text-amber-400" />
                    Knowledge Base
                  </CardTitle>
                  <CardDescription>Manage FAQ articles for AI responses</CardDescription>
                </div>
                <Button
                  onClick={() => {
                    setShowKbForm(true);
                    setEditingKbId(null);
                    setKbForm({ question: '', answer: '', category: 'general', active: true });
                  }}
                  className="bg-emerald-600 hover:bg-emerald-700"
                  data-testid="add-kb-article-btn"
                >
                  <Plus className="w-4 h-4 mr-2" />
                  Add Article
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {/* Search */}
              <div className="flex gap-3 mb-4">
                <div className="relative flex-1">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
                  <Input
                    placeholder="Search articles..."
                    value={kbSearch}
                    onChange={(e) => setKbSearch(e.target.value)}
                    className="input-dark pl-9"
                  />
                </div>
                <Button onClick={() => fetchKbArticles(1)} variant="outline">
                  <Search className="w-4 h-4" />
                </Button>
              </div>

              {/* KB Form Modal */}
              {showKbForm && (
                <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
                  <div className="bg-zinc-900 rounded-xl max-w-2xl w-full max-h-[80vh] overflow-hidden">
                    <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
                      <h3 className="font-semibold text-white">
                        {editingKbId ? 'Edit Article' : 'New Knowledge Base Article'}
                      </h3>
                      <Button variant="ghost" size="sm" onClick={() => setShowKbForm(false)}>
                        <XCircle className="w-5 h-5" />
                      </Button>
                    </div>
                    <div className="p-4 space-y-4 overflow-auto max-h-[60vh]">
                      <div>
                        <Label className="text-zinc-400">Question / Topic</Label>
                        <Input
                          value={kbForm.question}
                          onChange={(e) => setKbForm({ ...kbForm, question: e.target.value })}
                          className="input-dark mt-2"
                          placeholder="e.g., How do I use the Covered Call screener?"
                        />
                      </div>
                      <div>
                        <Label className="text-zinc-400">Answer</Label>
                        <textarea
                          value={kbForm.answer}
                          onChange={(e) => setKbForm({ ...kbForm, answer: e.target.value })}
                          className="w-full h-40 mt-2 px-3 py-2 rounded-lg bg-zinc-800/50 border border-zinc-700 text-white resize-none focus:outline-none focus:border-emerald-500"
                          placeholder="Provide a detailed answer..."
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <Label className="text-zinc-400">Category</Label>
                          <Select
                            value={kbForm.category}
                            onValueChange={(v) => setKbForm({ ...kbForm, category: v })}
                          >
                            <SelectTrigger className="input-dark mt-2">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="general">General</SelectItem>
                              <SelectItem value="billing">Billing</SelectItem>
                              <SelectItem value="technical">Technical</SelectItem>
                              <SelectItem value="screener">Screener</SelectItem>
                              <SelectItem value="pmcc">PMCC</SelectItem>
                              <SelectItem value="simulator">Simulator</SelectItem>
                              <SelectItem value="portfolio">Portfolio</SelectItem>
                              <SelectItem value="how_it_works">How It Works</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="flex items-center gap-3 pt-6">
                          <Switch
                            checked={kbForm.active}
                            onCheckedChange={(v) => setKbForm({ ...kbForm, active: v })}
                          />
                          <Label className="text-zinc-400">Active</Label>
                        </div>
                      </div>
                    </div>
                    <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
                      <Button variant="outline" onClick={() => setShowKbForm(false)}>Cancel</Button>
                      <Button onClick={handleSaveKbArticle} className="bg-emerald-600 hover:bg-emerald-700">
                        {editingKbId ? 'Update Article' : 'Create Article'}
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {/* Articles List */}
              {kbLoading ? (
                <div className="space-y-2">
                  {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
                </div>
              ) : kbArticles.length === 0 ? (
                <div className="text-center py-12 text-zinc-500">
                  <BookOpen className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>No knowledge base articles yet</p>
                  <p className="text-sm mt-2">Add articles to help AI generate better responses</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {kbArticles.map((article) => (
                    <div
                      key={article.id}
                      className="p-4 rounded-lg bg-zinc-800/50 border border-zinc-700 hover:border-zinc-600 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <h4 className="text-white font-medium">{article.question}</h4>
                            <Badge className={article.active ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-500/20 text-zinc-400'}>
                              {article.active ? 'Active' : 'Inactive'}
                            </Badge>
                            <Badge className="bg-violet-500/20 text-violet-400">{article.category}</Badge>
                          </div>
                          <p className="text-sm text-zinc-400 line-clamp-2">{article.answer}</p>
                        </div>
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setEditingKbId(article.id);
                              setKbForm({
                                question: article.question,
                                answer: article.answer,
                                category: article.category,
                                active: article.active
                              });
                              setShowKbForm(true);
                            }}
                            className="text-zinc-400 hover:text-white"
                          >
                            <Edit3 className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteKbArticle(article.id)}
                            className="text-red-400 hover:text-red-300"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* KB Pagination */}
              {kbPagination.pages > 1 && (
                <div className="flex items-center justify-between pt-4 border-t border-zinc-800 mt-4">
                  <span className="text-sm text-zinc-500">
                    Page {kbPagination.page} of {kbPagination.pages}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fetchKbArticles(kbPagination.page - 1)}
                      disabled={kbPagination.page <= 1}
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fetchKbArticles(kbPagination.page + 1)}
                      disabled={kbPagination.page >= kbPagination.pages}
                    >
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default AdminSupport;
