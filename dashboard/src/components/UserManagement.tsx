import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi, UserInfo, InvitationInfo } from '../api/client'
import { UserPlus, Trash2, Shield, Mail, Clock, CheckCircle, XCircle, Copy, RefreshCw } from 'lucide-react'

type TabType = 'users' | 'invitations'

function UserManagement() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabType>('users')
  const [showInviteForm, setShowInviteForm] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('viewer')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [copiedLink, setCopiedLink] = useState<string | null>(null)

  // Fetch users
  const { data: usersData, isLoading: usersLoading } = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.listUsers().then(res => res.data),
  })

  // Fetch invitations
  const { data: invitationsData, isLoading: invitationsLoading } = useQuery({
    queryKey: ['invitations'],
    queryFn: () => usersApi.listInvitations().then(res => res.data),
  })

  // Create invitation mutation
  const createInvitation = useMutation({
    mutationFn: (data: { email: string; role: string }) =>
      usersApi.createInvitation(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invitations'] })
      setSuccess(`Invitation created successfully! Copy the link from the Invitations tab.`)
      setShowInviteForm(false)
      setInviteEmail('')
      setInviteRole('viewer')
      setError(null)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to create invitation')
      setSuccess(null)
    },
  })

  // Update role mutation
  const updateRole = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) =>
      usersApi.updateRole(userId, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setSuccess('Role updated successfully')
      setError(null)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to update role')
      setSuccess(null)
    },
  })

  // Deactivate user mutation
  const deactivateUser = useMutation({
    mutationFn: (userId: number) => usersApi.deactivateUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setSuccess('User deactivated successfully')
      setError(null)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to deactivate user')
      setSuccess(null)
    },
  })

  // Revoke invitation mutation
  const revokeInvitation = useMutation({
    mutationFn: (invitationId: number) => usersApi.revokeInvitation(invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invitations'] })
      setSuccess('Invitation revoked')
      setError(null)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to revoke invitation')
      setSuccess(null)
    },
  })

  const handleInviteSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!inviteEmail.trim()) {
      setError('Email is required')
      return
    }
    createInvitation.mutate({ email: inviteEmail, role: inviteRole })
  }

  const copyInvitationLink = async (token: string) => {
    const link = `${window.location.origin}/accept-invitation?token=${token}`
    try {
      await navigator.clipboard.writeText(link)
      setCopiedLink(token)
      setTimeout(() => setCopiedLink(null), 2000)
    } catch {
      setError('Failed to copy link')
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const isExpired = (expiresAt: string) => {
    return new Date(expiresAt) < new Date()
  }

  return (
    <div className="bg-slate-800 rounded-lg p-6">
      {/* Status Messages */}
      {error && (
        <div className="mb-4 p-3 bg-red-900/30 border border-red-600 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}
      {success && (
        <div className="mb-4 p-3 bg-green-900/30 border border-green-600 rounded-lg text-green-400 text-sm">
          {success}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex gap-2">
          <button
            onClick={() => setActiveTab('users')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'users'
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-gray-400 hover:text-white'
            }`}
          >
            Users ({usersData?.total ?? 0})
          </button>
          <button
            onClick={() => setActiveTab('invitations')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'invitations'
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-gray-400 hover:text-white'
            }`}
          >
            Invitations ({invitationsData?.invitations?.filter(i => !i.accepted && !isExpired(i.expires_at)).length ?? 0})
          </button>
        </div>
        <button
          onClick={() => setShowInviteForm(!showInviteForm)}
          className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm font-medium transition-colors"
        >
          <UserPlus className="w-4 h-4" />
          Invite User
        </button>
      </div>

      {/* Invite Form */}
      {showInviteForm && (
        <form onSubmit={handleInviteSubmit} className="mb-6 p-4 bg-slate-700/50 rounded-lg">
          <h4 className="text-sm font-semibold text-white mb-4">Send Invitation</h4>
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="block text-xs text-gray-400 mb-1">Email Address</label>
              <input
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="user@example.com"
                className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div className="w-32">
              <label className="block text-xs text-gray-400 mb-1">Role</label>
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
              >
                <option value="viewer">Viewer</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <button
              type="submit"
              disabled={createInvitation.isPending}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
            >
              {createInvitation.isPending ? 'Sending...' : 'Send Invite'}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowInviteForm(false)
                setInviteEmail('')
                setInviteRole('viewer')
              }}
              className="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg text-sm transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Users Tab */}
      {activeTab === 'users' && (
        <div className="space-y-2">
          {usersLoading ? (
            <div className="flex justify-center py-8">
              <RefreshCw className="w-6 h-6 text-gray-400 animate-spin" />
            </div>
          ) : usersData?.users && usersData.users.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-xs text-gray-400 border-b border-slate-700">
                    <th className="pb-3 font-medium">User</th>
                    <th className="pb-3 font-medium">Role</th>
                    <th className="pb-3 font-medium">Status</th>
                    <th className="pb-3 font-medium">Last Login</th>
                    <th className="pb-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {usersData.users.map((user: UserInfo) => (
                    <tr key={user.id} className="border-b border-slate-700/50">
                      <td className="py-3">
                        <div>
                          <div className="font-medium text-white">{user.username}</div>
                          {user.email && (
                            <div className="text-xs text-gray-400">{user.email}</div>
                          )}
                        </div>
                      </td>
                      <td className="py-3">
                        <select
                          value={user.role}
                          onChange={(e) => updateRole.mutate({ userId: user.id, role: e.target.value })}
                          className={`px-2 py-1 rounded text-xs font-medium bg-slate-700 border border-slate-600 ${
                            user.role === 'admin' ? 'text-purple-400' : 'text-gray-300'
                          }`}
                        >
                          <option value="viewer">Viewer</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                      <td className="py-3">
                        <span className={`flex items-center gap-1 text-xs ${
                          user.is_active ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {user.is_active ? (
                            <CheckCircle className="w-3 h-3" />
                          ) : (
                            <XCircle className="w-3 h-3" />
                          )}
                          {user.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="py-3 text-sm text-gray-400">
                        {user.last_login ? formatDate(user.last_login) : 'Never'}
                      </td>
                      <td className="py-3 text-right">
                        {user.is_active && (
                          <button
                            onClick={() => {
                              if (confirm(`Are you sure you want to deactivate ${user.username}?`)) {
                                deactivateUser.mutate(user.id)
                              }
                            }}
                            className="p-1 text-red-400 hover:text-red-300 hover:bg-red-900/30 rounded"
                            title="Deactivate user"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400">
              No users found
            </div>
          )}
        </div>
      )}

      {/* Invitations Tab */}
      {activeTab === 'invitations' && (
        <div className="space-y-2">
          {invitationsLoading ? (
            <div className="flex justify-center py-8">
              <RefreshCw className="w-6 h-6 text-gray-400 animate-spin" />
            </div>
          ) : invitationsData?.invitations && invitationsData.invitations.length > 0 ? (
            <div className="space-y-3">
              {invitationsData.invitations.map((invitation: InvitationInfo) => {
                const expired = isExpired(invitation.expires_at)
                return (
                  <div
                    key={invitation.id}
                    className={`p-4 rounded-lg border ${
                      invitation.accepted
                        ? 'bg-green-900/20 border-green-700/50'
                        : expired
                        ? 'bg-red-900/20 border-red-700/50'
                        : 'bg-slate-700/50 border-slate-600'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <Mail className={`w-5 h-5 ${
                          invitation.accepted ? 'text-green-400' : expired ? 'text-red-400' : 'text-blue-400'
                        }`} />
                        <div>
                          <div className="font-medium text-white">{invitation.email}</div>
                          <div className="flex items-center gap-3 text-xs text-gray-400">
                            <span className="flex items-center gap-1">
                              <Shield className="w-3 h-3" />
                              {invitation.role}
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {invitation.accepted
                                ? `Accepted ${formatDate(invitation.accepted_at!)}`
                                : expired
                                ? 'Expired'
                                : `Expires ${formatDate(invitation.expires_at)}`}
                            </span>
                            <span>Invited by {invitation.invited_by_username}</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {invitation.accepted ? (
                          <span className="px-2 py-1 bg-green-600/30 text-green-400 rounded text-xs font-medium">
                            Accepted
                          </span>
                        ) : expired ? (
                          <span className="px-2 py-1 bg-red-600/30 text-red-400 rounded text-xs font-medium">
                            Expired
                          </span>
                        ) : (
                          <>
                            <button
                              onClick={() => copyInvitationLink(invitation.token)}
                              className="flex items-center gap-1 px-2 py-1 bg-slate-600 hover:bg-slate-500 rounded text-xs transition-colors"
                              title="Copy invitation link"
                            >
                              <Copy className="w-3 h-3" />
                              {copiedLink === invitation.token ? 'Copied!' : 'Copy Link'}
                            </button>
                            <button
                              onClick={() => {
                                if (confirm('Are you sure you want to revoke this invitation?')) {
                                  revokeInvitation.mutate(invitation.id)
                                }
                              }}
                              className="p-1 text-red-400 hover:text-red-300 hover:bg-red-900/30 rounded"
                              title="Revoke invitation"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400">
              No invitations sent yet
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default UserManagement
