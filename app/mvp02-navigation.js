// Select an existing working area before the canonical interface initializes.
// No server write, tool call or workflow execution follows from navigation.
(()=>{
  const areas={overview:'Overview',projects:'Projects',chat:'Chat',team:'Agents',
    skills:'Skills',memory:'Memory',workflows:'Loops',results:'Runs',
    improvements:'Improvements',workspace:'Stack & Git',maps:'Graph',connections:'Connections',hubs:'Hubs'};
  const area=new URLSearchParams(location.search).get('area');
  if(Object.hasOwn(areas,area)){
    localStorage.setItem('brain-tab',areas[area]);
    // Consume the entry link once. MAPS reloads the page to initialize its
    // canvas; leaving this parameter would override the newly selected tab.
    const destination=new URL(location.href);
    destination.searchParams.delete('area');
    history.replaceState(null,'',destination.pathname+destination.search+destination.hash);
  }
})();
