import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { ToastContainer } from '../ToastContainer'

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#F9FAFB' }}>
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 overflow-auto p-6" style={{ background: '#F9FAFB' }}>
          <Outlet />
        </main>
      </div>
      <ToastContainer />
    </div>
  )
}
