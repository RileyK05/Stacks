<script lang="ts">
  import Icon, { type IconName } from '$lib/components/Icon.svelte';

  let { children } = $props();

  const features: { icon: IconName; title: string; body: string }[] = [
    {
      icon: 'bookmark',
      title: 'Answers with receipts',
      body: 'Every answer cites the exact page or slide it came from.'
    },
    {
      icon: 'list-checks',
      title: 'Practice built from your material',
      body: 'Quizzes, study guides, and slides generated from your sources.'
    },
    {
      icon: 'users',
      title: 'Study together',
      body: 'Share a course with a join code — learners get the same tutor.'
    }
  ];
</script>

<div class="grid min-h-dvh lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
  <aside
    class="relative hidden overflow-hidden bg-[oklch(0.24_0.06_268)] p-12 text-white lg:flex lg:flex-col"
  >
    <div
      class="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:radial-gradient(white_1px,transparent_1px)] [background-size:22px_22px]"
      aria-hidden="true"
    ></div>
    <div
      class="pointer-events-none absolute -right-40 -top-40 h-[32rem] w-[32rem] rounded-full bg-[oklch(0.55_0.17_268)] opacity-30 blur-3xl"
      aria-hidden="true"
    ></div>
    <div
      class="pointer-events-none absolute -bottom-48 -left-24 h-[28rem] w-[28rem] rounded-full bg-[oklch(0.6_0.12_200)] opacity-20 blur-3xl"
      aria-hidden="true"
    ></div>

    <a href="/" class="relative flex items-center gap-2.5">
      <span class="flex h-9 w-9 items-center justify-center rounded-[10px] bg-white/15 ring-1 ring-white/20 backdrop-blur">
        <Icon name="book" class="h-5 w-5" />
      </span>
      <span class="font-display text-lg font-semibold tracking-tight">Course Assistant</span>
    </a>

    <div class="relative my-auto max-w-lg py-12">
      <p class="font-display text-5xl font-medium leading-[1.08] tracking-tight">
        Study from your <em class="font-normal italic text-[oklch(0.85_0.08_268)]">own</em> course material.
      </p>
      <p class="mt-5 text-lg leading-relaxed text-white/70">
        Upload your syllabus, slides, and notes, then ask questions and get answers grounded in
        them.
      </p>
      <ul class="mt-10 flex flex-col gap-5">
        {#each features as feature (feature.title)}
          <li class="flex gap-4">
            <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/15">
              <Icon name={feature.icon} class="h-[18px] w-[18px]" />
            </span>
            <span>
              <span class="block font-medium">{feature.title}</span>
              <span class="block text-sm text-white/60">{feature.body}</span>
            </span>
          </li>
        {/each}
      </ul>
    </div>
  </aside>

  <main class="flex flex-col px-5 py-8 sm:px-10">
    <a href="/" class="flex items-center gap-2.5 lg:hidden">
      <span class="flex h-8 w-8 items-center justify-center rounded-[10px] bg-accent text-on-accent shadow-card">
        <Icon name="book" class="h-[18px] w-[18px]" />
      </span>
      <span class="font-display text-[17px] font-semibold tracking-tight text-fg">Course Assistant</span>
    </a>
    <div class="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
      {@render children()}
    </div>
  </main>
</div>
