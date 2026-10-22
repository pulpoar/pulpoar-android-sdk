pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven {
            // Exactly what the README tells partners to add; -PpulpoMavenRepository points it at a directory to
            // test a candidate before it is published.
            val repository =
                providers
                    .gradleProperty("pulpoMavenRepository")
                    .getOrElse("https://assets.pulpoar.com/vision/pulpo-sdk/android/maven")
            url = if (repository.startsWith("https://")) uri(repository) else uri(file(repository))
            content { includeGroup("com.pulpoar") }
        }
    }
}

rootProject.name = "PulpoSdkConsumer"

include(":app")
