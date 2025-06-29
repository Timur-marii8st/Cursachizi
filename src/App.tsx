// src/App.tsx
import { useState } from 'react';
import Sidebar from './components/Sidebar';
import './styles/App.css'; 

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const toggleSidebar = () => {
    setIsSidebarOpen(!isSidebarOpen);
  };

  return (
    <div className="app-container">
      <button
        className={`menu-button ${isSidebarOpen ? 'open' : ''}`}
        onClick={toggleSidebar}
        aria-label="Open menu"
        aria-expanded={isSidebarOpen}
      >
        <span></span>
        <span></span>
        <span></span>
      </button>

      <Sidebar isOpen={isSidebarOpen} onClose={toggleSidebar} />

      <main className="main-content">
        <h1 className="title-cursive">chastie.</h1>
        <h1 style={{ marginTop: '-180px', color: 'rgba(40, 38, 38, 0.7)', fontWeight: 400 }}>Is all you need</h1>
        <div className="button-row">
          <button className="auth-button signup-button">Sign Up</button>
          <button className="auth-button login-button">Log In</button>
        </div>
      </main>
    </div>
  );
}

export default App;