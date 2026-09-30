# Java 8 → 11 Change Patterns

Before/after shapes for the changes a Java 11 upgrade actually needs. Each
keeps behaviour identical; none is a modernisation for its own sake.

## Maven compiler level

```xml
<!-- before -->
<properties>
  <maven.compiler.source>1.8</maven.compiler.source>
  <maven.compiler.target>1.8</maven.compiler.target>
</properties>

<!-- after -->
<properties>
  <maven.compiler.release>11</maven.compiler.release>
</properties>
```

When the level lives in the plugin instead:

```xml
<!-- before -->
<plugin>
  <artifactId>maven-compiler-plugin</artifactId>
  <version>3.1</version>
  <configuration>
    <source>1.8</source>
    <target>1.8</target>
    <encoding>UTF-8</encoding>
  </configuration>
</plugin>

<!-- after -->
<plugin>
  <artifactId>maven-compiler-plugin</artifactId>
  <version>3.8.1</version>
  <configuration>
    <release>11</release>
    <encoding>UTF-8</encoding>
  </configuration>
</plugin>
```

A property such as `<java.version>1.8</java.version>` that the compiler reads
through `${java.version}` is changed at the property: `<java.version>11</java.version>`.

## maven-war-plugin — version only

```xml
<!-- before -->
<plugin>
  <artifactId>maven-war-plugin</artifactId>
  <version>2.6</version>
  <configuration>
    <failOnMissingWebXml>false</failOnMissingWebXml>
    <warName>orders</warName>
  </configuration>
</plugin>

<!-- after: identical except <version> -->
<plugin>
  <artifactId>maven-war-plugin</artifactId>
  <version>3.4.0</version>
  <configuration>
    <failOnMissingWebXml>false</failOnMissingWebXml>
    <warName>orders</warName>
  </configuration>
</plugin>
```

## Removed Java EE module, WAR on WildFly

```xml
<dependency>
  <groupId>javax.xml.bind</groupId>
  <artifactId>jaxb-api</artifactId>
  <version>2.3.1</version>
  <scope>provided</scope>
</dependency>
<dependency>
  <groupId>javax.annotation</groupId>
  <artifactId>javax.annotation-api</artifactId>
  <version>1.3.2</version>
  <scope>provided</scope>
</dependency>
```

Tests that marshal outside the container additionally need:

```xml
<dependency>
  <groupId>org.glassfish.jaxb</groupId>
  <artifactId>jaxb-runtime</artifactId>
  <version>2.3.9</version>
  <scope>test</scope>
</dependency>
```

## Enforcer rule

```xml
<!-- before --> <requireJavaVersion><version>[1.8,1.9)</version></requireJavaVersion>
<!-- after  --> <requireJavaVersion><version>[11,)</version></requireJavaVersion>
```

## Gradle

```groovy
// before
sourceCompatibility = 1.8
targetCompatibility = 1.8

// after
java {
    toolchain { languageVersion = JavaLanguageVersion.of(11) }
}
```

or, where toolchains are not used, `sourceCompatibility = 11` /
`targetCompatibility = 11`. `gradle/wrapper/gradle-wrapper.properties`:
`distributionUrl` to a Gradle that runs on JDK 11 (5.0+).

## sun.misc.BASE64Encoder / BASE64Decoder

`BASE64Encoder.encode` wraps lines at 76 characters using the platform line
separator (`\n` on Linux); the MIME encoder wraps at 76 with `\r\n`. When the exact bytes matter (stored values,
signatures, a partner's parser), strip or normalise explicitly and say so in
the summary. When the old output was used without line breaks
(`encodeBuffer` → then `replaceAll("\\s", "")` and similar), the basic
encoder matches.

```java
// before
import sun.misc.BASE64Encoder;
import sun.misc.BASE64Decoder;
String token = new BASE64Encoder().encode(bytes);
byte[] raw = new BASE64Decoder().decodeBuffer(token);

// after
import java.util.Base64;
String token = Base64.getMimeEncoder().encodeToString(bytes);
byte[] raw = Base64.getMimeDecoder().decode(token);
```

`BASE64Decoder.decodeBuffer` declares `IOException`; `Base64` does not. If a
`catch (IOException e)` now guards nothing else, the compiler reports it as
unreachable — narrow that `try` rather than deleting handling other calls
still need.

## sun.reflect.Reflection.getCallerClass

```java
// before
Class<?> caller = sun.reflect.Reflection.getCallerClass(2);

// after
Class<?> caller = StackWalker.getInstance(StackWalker.Option.RETAIN_CLASS_REFERENCE)
        .getCallerClass();
```

Check the depth: `getCallerClass(2)` and `StackWalker.getCallerClass()` both
mean "the caller of the method that is asking" — verify against the call site.

## System class loader is no longer a URLClassLoader

```java
// before — ClassCastException on Java 9+
URL[] urls = ((URLClassLoader) ClassLoader.getSystemClassLoader()).getURLs();

// after
String[] entries = System.getProperty("java.class.path").split(File.pathSeparator);
```

Inside WildFly the loader is a JBoss Modules loader, never a
`URLClassLoader`, on any Java version — code doing this was already only
working outside the container. Say so in the summary.

### Adding jars to the class path at runtime (`addURL` through reflection)

Typical in a `ClassPathUpdater` / `ClasspathHacker` utility. Java 9+ has no
supported way to append to the system class path at runtime, so this is
never a one-line fix — but it must not be left as it is, because the cast
throws `ClassCastException` on the first call.

```java
// before — ClassCastException on Java 9+ at the cast
URLClassLoader sys = (URLClassLoader) ClassLoader.getSystemClassLoader();
Method addURL = URLClassLoader.class.getDeclaredMethod("addURL", URL.class);
addURL.setAccessible(true);
addURL.invoke(sys, url);

// after — keep the old behaviour where it still exists, and give every other
// runtime one class loader that owns the added entries
private static final List<URL> ADDED = new CopyOnWriteArrayList<>();
private static volatile URLClassLoader added;

public static synchronized void add(URL url) throws Exception {
    ClassLoader sys = ClassLoader.getSystemClassLoader();
    if (sys instanceof URLClassLoader) {                  // Java 8, some launchers
        Method addURL = URLClassLoader.class.getDeclaredMethod("addURL", URL.class);
        addURL.setAccessible(true);
        addURL.invoke(sys, url);
        return;
    }
    ADDED.add(url);                                        // Java 9+
    added = new URLClassLoader(ADDED.toArray(new URL[0]), sys);
}

/** The loader to use for classes from the added entries (the system loader on Java 8). */
public static ClassLoader loader() {
    URLClassLoader l = added;
    return l != null ? l : ClassLoader.getSystemClassLoader();
}
```

Keep the public method signatures; add `loader()` only if callers load
classes by name and can be pointed at it. If callers rely on
`Class.forName(name)` finding the added classes through the default loader,
that cannot be preserved on Java 9+ — say so in the summary, naming the
callers, so a human decides (a `-cp` entry, or a `Class-Path` manifest
entry, keeps it working without code).

## Java version parsing

```java
// before — "11.0.2".substring(2, 3) is "0"
int major = Integer.parseInt(System.getProperty("java.version").substring(2, 3));

// after
int major = Runtime.version().feature();
```

## `_` as an identifier

```java
// before
catch (Exception _) { }
// after
catch (Exception ignored) { }
```

## Mockito 1 → 2 in test sources

```java
// before
import org.mockito.runners.MockitoJUnitRunner;
import org.mockito.internal.util.reflection.Whitebox;

// after
import org.mockito.junit.MockitoJUnitRunner;
// Whitebox was removed: set the field through a constructor/setter the test
// already has access to, or plain reflection on the test's own class.
```

`anyString()` / `any(Foo.class)` no longer match `null` in Mockito 2. A test
stubbing with them and passing `null` now falls through to the default
answer; use `nullable(String.class)` to keep the old meaning.

`InvocationOnMock.getArgumentAt(i, Foo.class)` was removed in 2.x — use
`getArgument(i)` (the type is inferred). Any other `org.mockito.internal.*`
import is internal API that 2.x moved or removed: replace it with the public
API that does the same job.

`org.mockito.runners.MockitoJUnitRunner` still exists in 2.x (deprecated; a
subclass of `org.mockito.junit.MockitoJUnitRunner`) and is removed in 4.x.
The run rewrites that import mechanically once the build is on Mockito 2 —
do not spend a task on it, and do not count it as a failure if you see it.

`MockitoJUnitRunner` in 2.x is strict by default and reports unused stubs as
failures — `MockitoJUnitRunner.Silent` keeps 1.x behaviour when a task says
the test's meaning must not change.
