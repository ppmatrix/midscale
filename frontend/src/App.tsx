import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './hooks/useAuth'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import NetworkDetail from './pages/NetworkDetail'
import DeviceDetail from './pages/DeviceDetail'
import AuditLog from './pages/AuditLog'
import SystemHealth from './pages/SystemHealth'

function AppRoutes() {
  const { token, user } = useAuth()
  const isSuperuser = user?.is_superuser ?? false

  return (
    <Routes>
      <Route path="/login" element={token ? <Navigate to="/" /> : <Login />} />
      <Route path="/register" element={token ? <Navigate to="/" /> : <Register />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/networks/:networkId" element={<NetworkDetail />} />
          <Route path="/devices/:deviceId" element={<DeviceDetail />} />
          {isSuperuser && <Route path="/audit" element={<AuditLog />} />}
          {isSuperuser && <Route path="/health" element={<SystemHealth />} />}
        </Route>
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
