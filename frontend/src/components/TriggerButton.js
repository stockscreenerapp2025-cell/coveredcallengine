import React, { useState } from 'react';
import axios from 'axios';

export const TriggerButton = () => {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    if (!window.confirm("Trigger manual snapshot?")) return;
    setLoading(true);
    try {
      await axios.post('/api/admin/trigger-snapshot');
      alert("Success: Check dashboard in 5 minutes.");
    } catch (e) { alert("Error triggering snapshot."); }
    setTimeout(() => setLoading(false), 5000);
  };

  return (
    <button 
      onClick={handleClick} 
      disabled={loading}
      style={{padding: '10px', background: loading ? '#ccc' : '#007bff', color: 'white', borderRadius: '5px', cursor: 'pointer'}}
    >
      {loading ? "Processing..." : "🚀 Manual EOD Snapshot"}
    </button>
  );
};
