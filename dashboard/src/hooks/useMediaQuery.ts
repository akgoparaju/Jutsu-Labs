/**
 * useMediaQuery Hook
 * 
 * A responsive hook for detecting viewport size changes.
 * Mobile-first implementation with SSR safety and proper cleanup.
 * 
 * @example
 * const isMobile = useMediaQuery('(max-width: 639px)')
 * const isTablet = useMediaQuery('(min-width: 640px) and (max-width: 1023px)')
 * const isDesktop = useMediaQuery('(min-width: 1024px)')
 * 
 * @version 1.0.0
 * @part Responsive UI Foundation - Phase 1
 */

import { useState, useEffect } from 'react'

/**
 * Hook that returns whether a media query matches
 * 
 * @param query - Media query string (e.g., '(max-width: 639px)')
 * @returns boolean indicating if the media query matches
 */
export function useMediaQuery(query: string): boolean {
  // SSR safety: Check if window exists before accessing matchMedia
  const getInitialValue = (): boolean => {
    if (typeof window !== 'undefined') {
      return window.matchMedia(query).matches
    }
    // Default to false during SSR (assumes mobile-first, will update on client)
    return false
  }

  const [matches, setMatches] = useState<boolean>(getInitialValue)

  useEffect(() => {
    // Guard against SSR
    if (typeof window === 'undefined') {
      return
    }

    const mediaQuery = window.matchMedia(query)

    // Handler for media query changes
    const handler = (event: MediaQueryListEvent): void => {
      setMatches(event.matches)
    }

    // Set initial value (in case it changed between SSR and hydration)
    setMatches(mediaQuery.matches)

    // Modern browsers use addEventListener
    mediaQuery.addEventListener('change', handler)

    // Cleanup function removes listener on unmount
    return () => {
      mediaQuery.removeEventListener('change', handler)
    }
  }, [query])

  return matches
}

/**
 * Predefined breakpoint hooks for convenience
 * These align with the Tailwind breakpoints defined in tailwind.config.js
 */

/** Returns true if viewport is less than 480px (phones) */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 479px)')
}

/** Returns true if viewport is 480px-639px (large phones) */
export function useIsLargeMobile(): boolean {
  return useMediaQuery('(min-width: 480px) and (max-width: 639px)')
}

/** Returns true if viewport is less than 640px (all mobile devices) */
export function useIsMobileOrSmaller(): boolean {
  return useMediaQuery('(max-width: 639px)')
}

/** Returns true if viewport is 640px-1023px (tablets) */
export function useIsTablet(): boolean {
  return useMediaQuery('(min-width: 640px) and (max-width: 1023px)')
}

/** Returns true if viewport is 1024px or larger (desktops) */
export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 1024px)')
}

/** Returns true if viewport is 1280px or larger (large desktops) */
export function useIsLargeDesktop(): boolean {
  return useMediaQuery('(min-width: 1280px)')
}

export default useMediaQuery
